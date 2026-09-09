"""
Mock Aadhaar PKI — generate cryptographically real, legally harmless demo cards.

WHY THIS EXISTS
---------------
The showpiece of this project is verifying a UIDAI RSA signature on an Aadhaar
Secure QR. Doing that against *real* Aadhaar cards needs UIDAI's production
certificate and real people's ID documents. For an internal hackathon round both
are the wrong trade: the certificate is a procurement errand, and real cards drag
in consent, privacy and blur-the-screen problems for zero added technical merit.

So we run our own certificate authority instead.

This is NOT a shortcut or a fake demo. The payload format, the RSA-2048
PKCS#1 v1.5 signature, the SHA-256 digest, the gzip wrapper, the big-integer
encoding and the 0xFF field framing are all byte-for-byte what UIDAI emits. The
*only* difference is which private key signed it. `aadhaar_qr.py` runs its exact
production code path against these cards — nothing is stubbed or bypassed.

Swap `certs/mock_uidai.cer` for UIDAI's real certificate and the same code
verifies real cards. That is the whole point, and it is a strong thing to say to
a judge: "we demonstrate the mechanism against our own CA because we are not an
authorised UIDAI entity, and the verification path is identical."

It also means every demo document is synthetic. No teammate has to hand over
their Aadhaar, and nothing on screen ever needs blurring.

USAGE
-----
    python tools/mock_pki.py init
        Generate an RSA-2048 keypair and a self-signed certificate into certs/.

    python tools/mock_pki.py card --name "Asha Devi" --uid 234567890124
        Build a genuine signed card. Writes a QR image, a front image and the
        raw payload into demo_data/.

    python tools/mock_pki.py tamper --name "Asha Devi" --uid 234567890124
        Same card with one byte of the signed region flipped after signing.
        Signature verification MUST fail. This is demo step 2.

    python tools/mock_pki.py replay --name "Asha Devi" --uid 234567890124
        The replay attack: a genuine, correctly-signed QR from one person
        combined with a DIFFERENT face printed on the card front. This is the
        attack the verifier must catch, and the card to test the fix against.

Everything lands in demo_data/, which is gitignored — synthetic or not, demo
artefacts do not belong in version control.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import io
import random
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from PIL import Image, ImageDraw

# Must match aadhaar_qr.py exactly. If these drift, the mock stops exercising
# the real parser and the whole exercise is pointless.
DELIMITER = b"\xff"
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

# Same reason as aadhaar_qr.py: the payload is one very large decimal integer
# and Python 3.11+ caps int<->str conversion at 4300 digits by default.
sys.set_int_max_str_digits(100_000)

ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = ROOT / "certs"
DEMO_DIR = ROOT / "demo_data"
KEY_PATH = CERT_DIR / "mock_uidai_private.pem"
CERT_PATH = CERT_DIR / "mock_uidai.cer"


# ---------------------------------------------------------------------------
# Certificate authority
# ---------------------------------------------------------------------------

def cmd_init(_args: argparse.Namespace) -> None:
    CERT_DIR.mkdir(exist_ok=True)

    if KEY_PATH.exists():
        print(f"Key already exists at {KEY_PATH}. Delete it to regenerate.")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Named so nobody can mistake this for the real thing, in a screenshot or
    # in a hurry at 2am.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MOCK CA - NOT UIDAI"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Mock Aadhaar Signing (demo only)"),
    ])

    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_PATH.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    import hashlib
    fingerprint = hashlib.sha256(
        cert.public_bytes(serialization.Encoding.DER)
    ).hexdigest()

    print(f"Private key  -> {KEY_PATH}")
    print(f"Certificate  -> {CERT_PATH}")
    print(f"Fingerprint  -> {fingerprint}")
    print()
    print("Point the app at it, and pin it:")
    print(f"    set UIDAI_CERT_PATH={CERT_PATH}")
    print(f"    set UIDAI_CERT_FINGERPRINT={fingerprint}")
    print()
    print("Pinning matters: without it the app trusts whatever file sits at that")
    print("path, so anyone who drops a self-signed certificate into certs/ can")
    print("make their own forgeries verify as genuine.")
    print()
    print("Then restart uvicorn and check /health for uidai_certificate_loaded: true")


def _load_key() -> rsa.RSAPrivateKey:
    if not KEY_PATH.exists():
        raise SystemExit("No mock key found. Run: python tools/mock_pki.py init")
    return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)


# ---------------------------------------------------------------------------
# Photo generation
# ---------------------------------------------------------------------------

# A QR symbol tops out at version 40, which holds 7089 numeric characters.
# The payload is one decimal integer over the whole gzipped record, and decimal
# expansion costs about 2.41 digits per byte, so the entire record must stay
# under roughly 2900 bytes. Text fields and the 256-byte signature take their
# share, which leaves the photo a hard ceiling. Real Aadhaar QR photos are
# tiny, aggressively-compressed JPEG2000 thumbnails for exactly this reason.
PHOTO_BUDGET_BYTES = 1800


def _encode_photo(image: Image.Image) -> bytes:
    """
    Compress a portrait down until it fits PHOTO_BUDGET_BYTES.

    Steps down through size and JPEG quality rather than picking one fixed
    setting, so a caller's arbitrary --photo still produces a scannable card.
    """
    for side, quality in ((96, 60), (80, 50), (64, 45), (56, 35), (48, 30), (40, 25)):
        candidate = image.copy()
        candidate.thumbnail((side, side))
        buffer = io.BytesIO()
        candidate.convert("L").save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        if len(data) <= PHOTO_BUDGET_BYTES:
            return data

    raise SystemExit(
        "Could not compress the photo under the QR size budget. "
        "Try a smaller or simpler image."
    )


def _make_photo(seed: str, size: int = 160) -> bytes:
    """
    A deterministic placeholder portrait.

    Not a face — deliberately. Face-match against these will not produce a
    meaningful score, and pretending otherwise would be exactly the kind of
    overclaiming this project is trying to avoid. For a real face-match demo,
    pass --photo with a consenting teammate's picture or a synthetic face.

    What these ARE good for: proving the photo survives the signature round
    trip, and showing that the photo inside the signed payload differs from the
    one printed on a replayed card.
    """
    rng = random.Random(seed)
    base = (rng.randint(60, 200), rng.randint(60, 200), rng.randint(60, 200))
    image = Image.new("RGB", (size, size), base)
    draw = ImageDraw.Draw(image)

    # Head-and-shoulders silhouette, so it is visually obvious which photo is
    # which when two cards sit side by side on a projector.
    draw.ellipse([size * 0.30, size * 0.15, size * 0.70, size * 0.55],
                 fill=(rng.randint(0, 90), rng.randint(0, 90), rng.randint(0, 90)))
    draw.ellipse([size * 0.18, size * 0.55, size * 0.82, size * 1.15],
                 fill=(rng.randint(0, 90), rng.randint(0, 90), rng.randint(0, 90)))
    initials = "".join(part[0] for part in seed.split()[:2]).upper() or "?"
    draw.text((6, 6), initials, fill=(255, 255, 255))

    return _encode_photo(image)


def _load_photo(path: str | None, seed: str) -> bytes:
    if not path:
        return _make_photo(seed)
    return _encode_photo(Image.open(path).convert("RGB"))


# ---------------------------------------------------------------------------
# Payload construction — the part that must match UIDAI's format exactly
# ---------------------------------------------------------------------------

def build_payload(fields: dict[str, str], photo: bytes, key: rsa.RSAPrivateKey,
                  corrupt: bool = False) -> str:
    """
    Assemble, sign, compress and big-integer-encode a Secure QR payload.

    Layout of the signed region:
        field_0 0xFF field_1 0xFF ... field_15 0xFF <photo bytes>
    followed by a trailing 256-byte RSA signature over everything before it.

    email_mobile_flag is "0", meaning no trailing contact hashes — the parser
    reads that flag to know how far back from the signature the photo ends, so
    "0" keeps the photo slice unambiguous.

    `corrupt=True` flips one byte of the name AFTER signing, which is precisely
    what a forger editing a card would do and exactly what the signature exists
    to catch.
    """
    parts = [fields.get(name, "").encode("utf-8") for name in FIELD_ORDER]
    signed_region = DELIMITER.join(parts) + DELIMITER + photo

    signature = key.sign(signed_region, padding.PKCS1v15(), hashes.SHA256())

    if corrupt:
        mutable = bytearray(signed_region)
        # Flip a byte inside the name field, past the flag and reference_id.
        target = len(parts[0]) + 1 + len(parts[1]) + 1
        mutable[target] = mutable[target] ^ 0x01
        signed_region = bytes(mutable)

    data = signed_region + signature
    raw = gzip.compress(data)
    return str(int.from_bytes(raw, "big"))


def _render_qr(payload: str, path: Path) -> None:
    import qrcode

    # Secure QR payloads are long; version None + low error correction lets the
    # library pick the smallest symbol that fits.
    code = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L,
                         box_size=4, border=2)
    code.add_data(payload)
    code.make(fit=True)
    code.make_image(fill_color="black", back_color="white").save(path)


def _render_front(fields: dict[str, str], photo: bytes, path: Path, banner: str) -> None:
    """The printed front of the card: photo, name, DOB, number. All unsigned."""
    card = Image.new("RGB", (640, 400), (250, 248, 240))
    draw = ImageDraw.Draw(card)

    draw.rectangle([0, 0, 640, 46], fill=(220, 60, 60))
    draw.text((14, 16), banner, fill=(255, 255, 255))

    card.paste(Image.open(io.BytesIO(photo)), (28, 90))

    x = 220
    draw.text((x, 100), f"Name: {fields['name']}", fill=(20, 20, 20))
    draw.text((x, 130), f"DOB: {fields['dob']}", fill=(20, 20, 20))
    draw.text((x, 160), f"Gender: {fields['gender']}", fill=(20, 20, 20))
    draw.text((x, 190), f"Address: {fields['vtc']}, {fields['district']}", fill=(20, 20, 20))
    draw.text((x, 220), f"{fields['state']} - {fields['pincode']}", fill=(20, 20, 20))
    draw.text((28, 300), f"UID: {fields['_uid_display']}", fill=(20, 20, 20))
    draw.text((28, 340), "SYNTHETIC DEMO DOCUMENT - NOT A REAL AADHAAR",
              fill=(180, 40, 40))

    card.save(path)


def _fields_for(name: str, uid: str) -> dict[str, str]:
    stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    return {
        "email_mobile_flag": "0",
        # Real format: last four digits of the Aadhaar number, then a timestamp.
        "reference_id": uid[-4:] + stamp,
        "name": name,
        "dob": "01-01-1998",
        "gender": "F",
        "care_of": "C/O Demo",
        "district": "Pune",
        "landmark": "Near Demo Park",
        "house": "12",
        "location": "Demo Layout",
        "pincode": "411001",
        "post_office": "Pune GPO",
        "state": "Maharashtra",
        "street": "Demo Road",
        "sub_district": "Pune City",
        "vtc": "Pune",
        "_uid_display": f"{uid[:4]} {uid[4:8]} {uid[8:]}",
    }


def _emit(tag: str, fields: dict[str, str], qr_photo: bytes, front_photo: bytes,
          key: rsa.RSAPrivateKey, corrupt: bool) -> None:
    DEMO_DIR.mkdir(exist_ok=True)
    payload = build_payload(fields, qr_photo, key, corrupt=corrupt)

    (DEMO_DIR / f"{tag}_payload.txt").write_text(payload)
    _render_qr(payload, DEMO_DIR / f"{tag}_back_qr.png")
    _render_front(fields, front_photo, DEMO_DIR / f"{tag}_front.png",
                  banner=f"DEMO CARD - {tag.upper()}")

    print(f"  {tag}_front.png      front of card (photo, name - all UNSIGNED)")
    print(f"  {tag}_back_qr.png    back of card (the signed Secure QR)")
    print(f"  {tag}_payload.txt    raw payload, {len(payload)} digits")


def cmd_card(args: argparse.Namespace) -> None:
    key = _load_key()
    fields = _fields_for(args.name, args.uid)
    photo = _load_photo(args.photo, args.name)
    print(f"Genuine card for {args.name}:")
    _emit("genuine", fields, photo, photo, key, corrupt=False)
    print("\nExpect: QR_SIGNATURE_VALID -> GENUINE_SIGNED")


def cmd_tamper(args: argparse.Namespace) -> None:
    key = _load_key()
    fields = _fields_for(args.name, args.uid)
    photo = _load_photo(args.photo, args.name)
    print(f"Tampered card for {args.name} (one byte flipped after signing):")
    _emit("tampered", fields, photo, photo, key, corrupt=True)
    print("\nExpect: QR_SIGNATURE_INVALID -> FORGED_SIGNATURE")


def cmd_replay(args: argparse.Namespace) -> None:
    """
    The replay attack, built as an artefact you can actually upload.

    The QR is genuine and correctly signed — it carries the victim's photo
    inside it. The card front carries the ATTACKER's photo. Nothing about the
    signature is wrong, because the attacker never touched the signed bytes;
    they only reprinted the unsigned paper around them.

    A verifier that matches a live selfie against the printed front photo will
    pass the attacker. A verifier that matches against the photo inside the
    signed payload will catch them.
    """
    key = _load_key()
    fields = _fields_for(args.name, args.uid)
    victim_photo = _load_photo(args.photo, args.name)
    attacker_photo = _load_photo(args.attacker_photo, "Attacker Person")

    print(f"Replay card: {args.name}'s genuine signed QR, attacker's face on the front")
    _emit("replay", fields, victim_photo, attacker_photo, key, corrupt=False)
    print()
    print("Expect TODAY:      QR_SIGNATURE_VALID -> GENUINE_SIGNED + BOUND   (attack succeeds)")
    print("Expect AFTER FIX:  signature valid, but signed photo != front photo -> flagged")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="generate the mock CA keypair and certificate").set_defaults(func=cmd_init)

    for name, func, helptext in (
        ("card", cmd_card, "a genuine signed card"),
        ("tamper", cmd_tamper, "a card whose signature must fail"),
        ("replay", cmd_replay, "genuine QR + a different face on the front"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--name", default="Asha Devi")
        p.add_argument("--uid", default="234567890124",
                       help="12 digits; use a Verhoeff-valid number for a clean demo")
        p.add_argument("--photo", default=None, help="portrait to embed (optional)")
        if name == "replay":
            p.add_argument("--attacker-photo", default=None,
                           help="face printed on the card front (optional)")
        p.set_defaults(func=func)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
