"""
Aadhaar QR decoding and UIDAI digital-signature verification.

There are two generations of Aadhaar QR code and they are completely different
animals. Your demo needs to detect which one it is looking at, because only one
of them can actually be verified.

V1 (legacy, printed on older cards)
    Payload is plain XML: <PrintLetterBarcodeData uid="..." name="..." .../>
    There is NO signature. Anyone can author this string in a text editor and
    render a QR from it. If your app reports "genuine" for a V1 QR, your app is
    lying. We return UNSIGNED and refuse to give a genuine verdict.

V2 (Secure QR, current)
    Payload is a very long decimal integer string. Pipeline:
        decimal string -> big integer -> raw bytes -> gzip decompress
        -> 0xFF-delimited text fields, then a JPEG2000 photo,
           then optional SHA-256 mobile/email hashes,
           then a trailing 256-byte RSA signature.
    The signature is SHA256-with-RSA (PKCS#1 v1.5) over every byte that
    precedes it, made with UIDAI's private key. We verify it against UIDAI's
    published public certificate.

    Verifying that signature proves ONE thing precisely: these exact field
    values were issued by UIDAI and have not been altered by a single bit.
    It does NOT prove the person handing you the document is the subject of it.
    That gap is what the face-match module closes.

Field ordering in V2 has shifted between UIDAI spec revisions. Confirm the
index map below against the current "Aadhaar Secure QR Code" spec before the
demo, and keep FIELD_ORDER in one place so a spec change is a one-line fix.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import sys
import zlib
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, load_pem_public_key
from cryptography.x509 import load_der_x509_certificate, load_pem_x509_certificate

# Python 3.11+ refuses int <-> str conversions beyond 4300 digits as a
# denial-of-service guard. A Secure QR payload is a decimal integer covering the
# whole compressed record including the photo, which routinely runs past that,
# so `int(payload)` raises ValueError on a perfectly genuine card. Raise the
# ceiling deliberately: the input here is already length-capped upstream by
# MAX_UPLOAD_BYTES, so the DoS concern the limit exists for does not apply.
sys.set_int_max_str_digits(100_000)

SIGNATURE_LENGTH = 256  # RSA-2048 signature, always the final 256 bytes
HASH_LENGTH = 32        # SHA-256 digest of mobile / email, when present
DELIMITER = 0xFF
QR_WORKING_EDGE = 3072

GZIP_MAGIC = b"\x1f\x8b"

# Legacy Secure QR text fields. Some newer Secure QR payloads prepend a
# format/version field (for example "V5") before the contact-present flag.
# Keep the canonical demographic order separate so the parser can support
# both layouts without silently shifting every field by one position.
FIELD_ORDER = (
    "email_mobile_flag",
    "reference_id",
    "name",
    "dob",
    "gender",
    "care_of",
    "district",
    "landmark",
    "house",
    "location",
    "pincode",
    "post_office",
    "state",
    "street",
    "sub_district",
    "vtc",
)

VERSION_FIELD = "qr_format_version"


class QRDecodeError(Exception):
    """Payload could not be decoded as any known Aadhaar QR format."""


@dataclass
class AadhaarQRResult:
    version: str                       # "V1" | "V2" | "UNKNOWN"
    signature_verified: bool | None    # None when the format carries no signature
    fields: dict[str, Any] = field(default_factory=dict)
    photo_jp2: bytes | None = None     # raw JPEG2000 bytes, held in memory only
    reasons: list[str] = field(default_factory=list)
    # Diagnostic context for a decode failure. Kept out of `reasons` so that
    # free-form error text never masquerades as a translatable reason code.
    detail: dict[str, Any] = field(default_factory=dict)

    # Fields that identify a person directly and must never be rendered whole
    # on a screen someone might photograph, or written to a log.
    #
    # This used to mask the reference_id alone and return the name, date of
    # birth and full address untouched — which is the identifying set, not a
    # safe remainder. The project's own constraint is that a real document on
    # screen must not leak identifiers; masking the number while displaying
    # "name, DOB, house, street, village, pincode" satisfies the letter of
    # that and none of its purpose.
    _SENSITIVE_FIELDS = (
        "name", "dob", "care_of", "house", "street", "landmark",
        "location", "vtc", "post_office", "sub_district", "district",
    )

    def redacted(self) -> dict[str, Any]:
        """
        Field view safe to log or render on a demo screen.

        Verification does not need to display who someone is. The verdict, the
        reason codes and the signature result carry the whole finding; the
        demographic payload is incidental to it. So identifying fields are
        reduced to a shape indicator rather than passed through — enough for an
        operator to see that a field was present and populated, not enough to
        identify the holder from a screenshot.
        """
        out = dict(self.fields)

        ref = out.get("reference_id") or ""
        if len(ref) >= 4:
            # reference_id starts with the last 4 digits of the Aadhaar number.
            out["reference_id"] = "XXXX" + ref[4:]

        for key in self._SENSITIVE_FIELDS:
            value = out.get(key)
            if isinstance(value, str) and value.strip():
                # Keep the first character so an operator can still sanity-check
                # that OCR and the signed payload refer to the same record,
                # without the screen carrying a legible identity.
                out[key] = value.strip()[0] + "*" * (len(value.strip()) - 1)

        # State and pincode stay: they are coarse enough not to identify anyone
        # on their own, and they make the demo legible as a real record.
        out.pop("photo_present", None)
        return out


# ---------------------------------------------------------------------------
# QR image -> payload string
# ---------------------------------------------------------------------------

def read_qr_payloads(image_bytes: bytes) -> list[str]:
    """
    Extract QR payloads from real-world Aadhaar photos and screenshots.

    The QR on the newer two-sided card can be relatively small in a phone
    screenshot. A single full-image pyzbar pass is therefore too brittle.

    We try:
      1. the original image,
      2. grayscale/autocontrast,
      3. 2x and 4x upscaling,
      4. contrast + sharpening,
      5. adaptive and Otsu thresholding,
      6. OpenCV QRCodeDetector as a second decoder.

    Cropping is intentionally conservative: first try the whole image, then
    likely QR regions, so we don't accidentally throw away a QR that is not
    in the expected location.
    """
    from PIL import Image, ImageEnhance, ImageOps
    from pyzbar.pyzbar import decode as zbar_decode

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if max(image.size) > QR_WORKING_EDGE:
        scale = QR_WORKING_EDGE / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    candidates: list[Image.Image] = [image]

    gray = ImageOps.autocontrast(image.convert("L"))
    candidates.append(gray)

    # Larger QR modules become much easier for barcode decoders to resolve.
    scaled_sizes: set[tuple[int, int]] = set()
    for scale in (2, 3, 4):
        bounded_scale = min(scale, QR_WORKING_EDGE / max(gray.size))
        if bounded_scale <= 1:
            continue
        size = (
            max(1, round(gray.width * bounded_scale)),
            max(1, round(gray.height * bounded_scale)),
        )
        if size not in scaled_sizes:
            candidates.append(gray.resize(size, Image.Resampling.LANCZOS))
            scaled_sizes.add(size)

    enhanced = ImageEnhance.Contrast(gray).enhance(1.8)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(2.0)
    enhanced_scale = min(3, QR_WORKING_EDGE / max(enhanced.size))
    if enhanced_scale > 1:
        candidates.append(enhanced.resize(
            (
                max(1, round(enhanced.width * enhanced_scale)),
                max(1, round(enhanced.height * enhanced_scale)),
            ),
            Image.Resampling.LANCZOS,
        ))
    else:
        candidates.append(enhanced)

    # Adaptive thresholding is useful when the card has uneven lighting.
    try:
        import cv2
        import numpy as np

        gray_np = np.asarray(gray, dtype=np.uint8)
        blurred = cv2.GaussianBlur(gray_np, (3, 3), 0)

        otsu = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]
        adaptive = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )

        for processed in (otsu, adaptive):
            pil = Image.fromarray(processed)
            threshold_scale = min(3, QR_WORKING_EDGE / max(pil.size))
            if threshold_scale > 1:
                pil = pil.resize(
                    (
                        max(1, round(pil.width * threshold_scale)),
                        max(1, round(pil.height * threshold_scale)),
                    ),
                    Image.Resampling.NEAREST,
                )
            candidates.append(pil)
    except ImportError:
        pass

    # Try likely QR areas as well. These are overlapping crops rather than a
    # single hard-coded box, so the detector remains useful if the card is
    # rotated, slightly cropped, or photographed at a different framing.
    width, height = image.size
    qr_regions = [
        (int(width * 0.55), 0, width, int(height * 0.72)),
        (int(width * 0.45), 0, width, int(height * 0.85)),
        (int(width * 0.35), 0, width, height),
    ]

    for box in qr_regions:
        crop = image.crop(box)
        crop_gray = ImageOps.autocontrast(crop.convert("L"))
        crop_sizes: set[tuple[int, int]] = set()
        for scale in (3, 4):
            bounded_scale = min(scale, QR_WORKING_EDGE / max(crop_gray.size))
            if bounded_scale <= 1:
                continue
            size = (
                max(1, round(crop_gray.width * bounded_scale)),
                max(1, round(crop_gray.height * bounded_scale)),
            )
            if size not in crop_sizes:
                candidates.append(crop_gray.resize(size, Image.Resampling.LANCZOS))
                crop_sizes.add(size)

    seen: list[str] = []

    def add_payload(value: str) -> None:
        value = value.strip()
        if value and value not in seen:
            seen.append(value)

    # Decoder 1: pyzbar / ZBar.
    for candidate in candidates:
        try:
            for symbol in zbar_decode(candidate):
                add_payload(symbol.data.decode("utf-8", errors="replace"))
            if seen:
                return seen
        except Exception:
            continue

    # Decoder 2: OpenCV. This can succeed where ZBar misses a small or noisy
    # QR, and it is already a natural dependency for the face/liveness stack.
    try:
        import cv2
        import numpy as np

        detector = cv2.QRCodeDetector()

        for candidate in candidates:
            array = np.asarray(candidate)
            if array.ndim == 2:
                bgr = cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
            else:
                bgr = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)

            try:
                value, points, _ = detector.detectAndDecode(bgr)
                if value:
                    add_payload(value)
            except Exception:
                pass

            # Multi-code API can be more tolerant of QR placement.
            try:
                values, _, _ = detector.detectAndDecodeMulti(bgr)
                if values:
                    for value in values:
                        if value:
                            add_payload(value)
            except Exception:
                pass

            if seen:
                return seen
    except ImportError:
        pass

    return seen


# ---------------------------------------------------------------------------
# Payload -> structured result
# ---------------------------------------------------------------------------

def parse_payload(payload: str, uidai_public_key: rsa.RSAPublicKey | None) -> AadhaarQRResult:
    payload = payload.strip()

    if payload.startswith("<?xml") or "PrintLetterBarcodeData" in payload:
        return _parse_v1(payload)

    if payload.isdigit():
        return _parse_v2(payload, uidai_public_key)

    raise QRDecodeError("Payload is neither legacy XML nor a Secure QR integer string")


def _parse_v1(payload: str) -> AadhaarQRResult:
    import xml.etree.ElementTree as ElementTree

    try:
        node = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise QRDecodeError(f"Malformed V1 XML: {exc}") from exc

    attributes = {key.lower(): value for key, value in node.attrib.items()}
    return AadhaarQRResult(
        version="V1",
        signature_verified=None,
        fields={
            "reference_id": (attributes.get("uid") or "")[-4:],
            "name": attributes.get("name", ""),
            "dob": attributes.get("dob") or attributes.get("yob", ""),
            "gender": attributes.get("gender", ""),
            "pincode": attributes.get("pc", ""),
        },
        reasons=["QR_V1_LEGACY_UNSIGNED"],
    )


def _decompress(raw: bytes) -> bytes:
    if raw[:2] == GZIP_MAGIC:
        return gzip.decompress(raw)
    # Some encoders emit a bare deflate stream. Try both wrappers before failing.
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    return raw  # already-plain payloads exist in test fixtures


def _split_text_fields(data: bytes, count: int) -> tuple[list[bytes], int]:
    """
    Take the first `count` 0xFF-delimited fields.

    We deliberately do NOT split the whole buffer on 0xFF: the embedded
    JPEG2000 photo is binary and contains 0xFF bytes in its marker segments,
    so a naive `data.split(b"\\xff")` shreds the image and shifts every
    subsequent offset. Scan for exactly the delimiters we need and stop.
    """
    fields: list[bytes] = []
    start = 0
    cursor = 0
    while len(fields) < count:
        cursor = data.find(bytes([DELIMITER]), start)
        if cursor == -1:
            raise QRDecodeError(
                f"Expected {count} delimited fields, found {len(fields)}"
            )
        fields.append(data[start:cursor])
        start = cursor + 1
    return fields, start


def _parse_v2(payload: str, uidai_public_key: rsa.RSAPublicKey | None) -> AadhaarQRResult:
    try:
        big_integer = int(payload)
    except ValueError as exc:
        raise QRDecodeError("Secure QR payload is not a valid integer") from exc

    byte_length = (big_integer.bit_length() + 7) // 8
    raw = big_integer.to_bytes(byte_length, "big")
    data = _decompress(raw)

    if len(data) <= SIGNATURE_LENGTH:
        raise QRDecodeError("Payload too short to contain a signature")

    reasons: list[str] = []

    # --- signature verification, over everything before the trailing 256 bytes
    signed_region = data[:-SIGNATURE_LENGTH]
    signature = data[-SIGNATURE_LENGTH:]

    signature_verified: bool | None
    if uidai_public_key is None:
        signature_verified = None
        reasons.append("UIDAI_CERT_NOT_CONFIGURED")
    else:
        try:
            uidai_public_key.verify(
                signature,
                signed_region,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            signature_verified = True
            reasons.append("QR_SIGNATURE_VALID")
        except Exception:
            signature_verified = False
            reasons.append("QR_SIGNATURE_INVALID")

    # --- text fields
    #
    # Older Secure QR payloads start directly with the email/mobile-present
    # flag. Newer payloads can prepend a format marker such as "V5". Detect
    # that marker instead of assuming the first field is always the flag.
    first_fields, cursor_after_first = _split_text_fields(
        signed_region, 1
    )
    first_value = first_fields[0].decode("utf-8", errors="replace").strip()

    if first_value.upper().startswith("V") and first_value[1:].isdigit():
        remaining_fields, photo_start = _split_text_fields(
            signed_region[cursor_after_first:], len(FIELD_ORDER)
        )
        # `_split_text_fields` above starts at zero relative to the slice.
        # Convert its returned offset back into the original signed region.
        photo_start += cursor_after_first

        fields = {
            name: value.decode("utf-8", errors="replace")
            for name, value in zip(FIELD_ORDER, remaining_fields)
        }
        fields[VERSION_FIELD] = first_value
    else:
        text_fields, photo_start = _split_text_fields(
            signed_region, len(FIELD_ORDER)
        )
        fields = {
            name: value.decode("utf-8", errors="replace")
            for name, value in zip(FIELD_ORDER, text_fields)
        }

    # --- trailing contact hashes, counted backwards from the signature
    flag = fields.get("email_mobile_flag", "")
    trailing_hashes = _expected_hash_count(flag)
    photo_end = len(signed_region) - (trailing_hashes * HASH_LENGTH)
    if photo_end <= photo_start:
        raise QRDecodeError("Photo segment resolved to a negative length")

    photo = signed_region[photo_start:photo_end]

    # The trailing SHA-256 mobile/email digests sit between `photo_end` and the
    # signature. They are deliberately NOT surfaced: verify_contact_hash() can
    # confirm a user-supplied number against them, but that requires the user
    # to type their mobile during the demo, and returning the digests in the
    # response would put hashed contact details on the wire for no gain. Slice
    # them here if that check is ever wired up.
    fields["photo_present"] = bool(photo)
    fields["contact_hash_count"] = trailing_hashes

    return AadhaarQRResult(
        version="V2",
        signature_verified=signature_verified,
        fields=fields,
        photo_jp2=photo or None,
        reasons=reasons,
    )


def _expected_hash_count(flag: str) -> int:
    """
    Index 0 of the payload signals which contact fields were hashed in.
    Conventionally: 0=none, 1=email only, 2=mobile only, 3=both.
    Unknown values fall back to 0 rather than guessing an offset, because a
    wrong guess silently corrupts the photo slice.
    """
    digits = "".join(ch for ch in flag if ch.isdigit())
    return {"0": 0, "1": 1, "2": 1, "3": 2}.get(digits[-1:], 0)


def verify_contact_hash(contact_value: str, last_four: str, digest: bytes) -> bool:
    """
    Optional extra binding: confirm a user-supplied mobile/email matches the
    hash inside the signed payload.

    UIDAI's construction is sha256(contact + last_four_of_aadhaar), iterated a
    number of times derived from the last digit. Because the iteration rule has
    changed across revisions, we try single and iterated forms rather than
    hardcoding one. Only useful if the user types their number during the demo.
    """
    base = (contact_value + last_four).encode()
    single = hashlib.sha256(base).digest()
    if single == digest:
        return True

    iterations = int(last_four[-1]) if last_four[-1:].isdigit() else 0
    current = base
    for _ in range(max(iterations, 1)):
        current = hashlib.sha256(current).hexdigest().encode()
    return bytes.fromhex(current.decode()) == digest


# ---------------------------------------------------------------------------
# Certificate loading
# ---------------------------------------------------------------------------

def certificate_fingerprint(path: str) -> str | None:
    """
    SHA-256 fingerprint of the signing certificate, lowercase hex.

    Taken over the certificate's DER encoding, so the same certificate gives
    the same fingerprint whether it was stored as PEM or DER.

    This is the one place a hash genuinely belongs in this project. Hashing an
    uploaded document proves nothing, because there is no trusted reference to
    compare it against — but here there *is* one: the fingerprint you recorded
    when you fetched the certificate from UIDAI.
    """
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError:
        return None

    for loader in (load_pem_x509_certificate, load_der_x509_certificate):
        try:
            certificate = loader(blob)
        except Exception:
            continue
        der = certificate.public_bytes(Encoding.DER)
        return hashlib.sha256(der).hexdigest()

    return None


def load_uidai_public_key(
    path: str,
    expected_fingerprint: str | None = None,
) -> rsa.RSAPublicKey | None:
    """
    Load UIDAI's signing certificate (PEM or DER) or a bare public key.

    `expected_fingerprint` pins it. Without pinning, the trust decision is
    "whatever file happens to sit at this path", which means anyone who can
    drop a self-signed certificate into certs/ can make every forgery they
    sign validate as genuine — the signature check would still pass, against
    the wrong key. Pinning turns the certificate into something the code
    verifies rather than something it merely reads.

    A mismatch returns None rather than loading anyway. Refusing to verify is
    the safe failure here: it degrades to UNVERIFIABLE, whereas trusting an
    unexpected key degrades to confidently wrong.

    If a judge asks how you know the key is genuine, "we pinned the SHA-256
    fingerprint we recorded when we fetched it" is a real answer; "we found it
    on GitHub" is not.
    """
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError:
        return None

    if expected_fingerprint:
        actual = certificate_fingerprint(path)
        if actual is None or actual.lower() != expected_fingerprint.strip().lower():
            return None

    for loader in (load_pem_x509_certificate, load_der_x509_certificate):
        try:
            return loader(blob).public_key()
        except Exception:
            continue
    try:
        # A bare public key carries no certificate to fingerprint, so pinning
        # cannot apply to it. Refuse rather than silently accepting an
        # unpinnable key when the operator asked for pinning.
        if expected_fingerprint:
            return None
        return load_pem_public_key(blob)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def verify_aadhaar_image(
    image_bytes: bytes,
    uidai_public_key: rsa.RSAPublicKey | None,
) -> AadhaarQRResult:
    payloads = read_qr_payloads(image_bytes)
    if not payloads:
        return AadhaarQRResult(
            version="UNKNOWN",
            signature_verified=None,
            reasons=["QR_NOT_FOUND"],
        )

    last_error: Exception | None = None
    for payload in payloads:
        try:
            return parse_payload(payload, uidai_public_key)
        except QRDecodeError as exc:
            last_error = exc
    return AadhaarQRResult(
        version="UNKNOWN",
        signature_verified=None,
        # Only the code. The raw exception message used to ride along here as a
        # second "reason code", which then flowed through assess() into the
        # audit database and out to the UI, where REASON_TEXT has no entry to
        # translate it. Diagnostic detail belongs in `detail`, not in a list
        # that is contractually reason codes.
        reasons=["QR_DECODE_FAILED"],
        detail={"error": str(last_error)[:200]} if last_error else {},
    )
