"""
FastAPI application.

Endpoints
    POST /verify/aadhaar    QR decode + signature verify + Verhoeff + ELA
    POST /verify/pan        OCR + structural check + ELA
    POST /verify/passport   MRZ parse + ICAO 9303 check digits + ELA
    POST /verify/marksheet  OCR + arithmetic/range checks + ELA + baselines
    POST /verify/face       ID photo vs live frames, in-memory only
    POST /verify/aadhaar-full  QR verify AND bind to a live selfie in one call
    GET  /dashboard/history
    GET  /dashboard/summary
    GET  /reasons           the full reason-code dictionary, for the UI
    GET  /health

Every response carries `disclaimer`. It is not decoration. Your own constraints
say no claim of official government verification, and the single most likely way
that constraint gets broken is a frontend that renders a green tick without
context. Putting the text in the payload means the frontend has to actively
discard it to mislead someone.
"""


from __future__ import annotations

import io
from difflib import SequenceMatcher
from typing import Literal

import pymupdf
from PIL import Image, UnidentifiedImageError

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import aadhaar_qr
import ela
import face_match
import forensics
import marksheet
import ocr
import pan
import passport
import verhoeff
from config import settings
from store import AuditStore
from verdict import REASON_TEXT, assess

DISCLAIMER = (
    "This tool checks whether a document is internally consistent and, for "
    "Aadhaar, whether its QR payload carries a valid UIDAI signature. It does "
    "not query any government database and is not official verification."
)

app = FastAPI(title="Document & Identity Verification", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = AuditStore(settings.database_path)
UIDAI_KEY = aadhaar_qr.load_uidai_public_key(
    settings.uidai_cert_path,
    expected_fingerprint=settings.uidai_cert_fingerprint or None,
)
# Reported at /health so an operator can see which certificate is actually in
# use, and whether it was pinned. A key loaded from an unpinned path is not the
# same trust claim as one whose fingerprint we checked.
UIDAI_CERT_FINGERPRINT = aadhaar_qr.certificate_fingerprint(settings.uidai_cert_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


async def read_upload(upload: UploadFile) -> bytes:
    # Read one byte beyond the limit so large uploads are rejected without
    # first copying the entire file into application memory.
    try:
        payload = await upload.read(settings.max_upload_bytes + 1)
    except Exception as exc:
        raise HTTPException(400, "Could not read the uploaded file.") from exc
    if not payload:
        raise HTTPException(400, "Empty upload")
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(413, "File exceeds the configured size limit")
    return payload


def validate_image_upload(data: bytes) -> bytes:
    """Reject corrupt, unsupported, animated, or decompression-bomb images."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            source_format = (image.format or "").upper()
            width, height = image.size
            if source_format not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(
                    415,
                    "Unsupported image format. Upload JPEG, PNG, or WebP.",
                )
            if width < 1 or height < 1:
                raise HTTPException(400, "The uploaded image has invalid dimensions.")
            if width * height > settings.max_image_pixels:
                raise HTTPException(
                    413,
                    "Image dimensions exceed the configured pixel limit.",
                )
            if getattr(image, "is_animated", False):
                raise HTTPException(415, "Animated images are not supported.")
            # Force pixel decoding here so truncated/corrupt inputs become a
            # client error at the API boundary rather than a later OCR 500.
            image.load()
    except HTTPException:
        raise
    except MemoryError as exc:
        raise HTTPException(413, "Image could not be decoded within memory limits.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(400, "Upload is not a readable image.") from exc
    return data


async def read_live_frames(frames: list[UploadFile]) -> list[bytes]:
    if len(frames) < 3:
        raise HTTPException(
            status_code=400,
            detail="At least 3 live frames are required for face verification.",
        )
    if len(frames) > settings.max_face_frames:
        raise HTTPException(
            status_code=413,
            detail=f"At most {settings.max_face_frames} live frames are accepted.",
        )

    payloads: list[bytes] = []
    total = 0
    for frame in frames:
        payload = validate_image_upload(await read_upload(frame))
        total += len(payload)
        if total > settings.max_face_burst_bytes:
            raise HTTPException(413, "Live-frame burst exceeds the total size limit.")
        payloads.append(payload)
    return payloads


def consent_gate(consent_subject: str | None) -> str:
    """
    Enforces the teammate-consent rule for anything touching a live face.
    """
    if not settings.require_consent_subject:
        return consent_subject or "unspecified"
    if not consent_subject:
        raise HTTPException(
            400,
            "consent_subject is required. Name the teammate who agreed to have "
            "their face and ID used, and add them to CONSENT_SUBJECTS.",
        )
    if consent_subject.strip().lower() not in settings.consent_subjects:
        raise HTTPException(
            403,
            f"'{consent_subject}' is not in the consent list. Ask them directly, "
            "then add them to CONSENT_SUBJECTS.",
        )
    return consent_subject.strip().lower()


def envelope(assessment, extra: dict, record_id: str) -> dict:
    return {
        "record_id": record_id,
        "verdict": assessment.verdict.value,
        "headline": assessment.headline(),
        "decided_by": assessment.decided_by.value if assessment.decided_by else None,
        "identity_binding": assessment.identity_binding.value,
        "reasons": assessment.reasons,
        "advisory": assessment.advisory,
        "details": extra,
        "disclaimer": DISCLAIMER,
    }


def rasterise_if_pdf(data: bytes, content_type: str | None = None) -> bytes:
    """
    Turn a PDF upload into a JPEG of its first page; pass images through.

    Judges and users hand this system e-Aadhaar and DigiLocker PDFs, because
    that is the form a downloaded government document usually takes. Only the
    marksheet endpoint handled that, so the Aadhaar and PAN endpoints raised
    an unhandled exception and returned HTTP 500 on a perfectly ordinary
    upload. A crash reads as a broken product; a clear refusal does not.

    Detection is by magic bytes rather than `content_type`, which the client
    supplies and browsers frequently get wrong (`application/octet-stream` is
    common). The declared type is accepted as a fallback hint only.
    """
    # PDF requires a header within the first 1024 bytes. Content-Type is not a
    # format check: clients frequently send a wrong or generic value.
    looks_like_pdf = b"%PDF-" in data[:1024]
    if not looks_like_pdf:
        return validate_image_upload(data)

    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read that PDF: {type(exc).__name__}",
        ) from exc

    try:
        if pdf.needs_pass:
            raise HTTPException(400, "Password-protected PDFs are not supported.")
        if len(pdf) == 0:
            raise HTTPException(status_code=400, detail="That PDF has no pages.")
        # 2x matrix: Secure QR modules are small, and rasterising at page scale
        # loses enough detail that the decoder misses the code entirely.
        page = pdf[0]
        pixel_width = max(1, round(page.rect.width * 2))
        pixel_height = max(1, round(page.rect.height * 2))
        if pixel_width * pixel_height > settings.max_image_pixels:
            raise HTTPException(413, "PDF page dimensions exceed the pixel limit.")
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("jpeg")
    except HTTPException:
        raise
    except MemoryError as exc:
        raise HTTPException(413, "PDF could not be rendered within memory limits.") from exc
    except Exception as exc:
        raise HTTPException(400, "Could not render the first PDF page.") from exc
    finally:
        pdf.close()


def crosscheck_printed_against_signed(qr_result, text_result) -> list[str]:
    """
    Compare what is PRINTED on the card against what the signature covers.

    A valid signature proves the QR payload came from UIDAI unaltered. It says
    nothing whatsoever about the ink around it. So the printed number and name
    have to be read back and checked against the signed fields — otherwise a
    genuine QR lifted onto a different person's card passes every test.

    Two checks, with deliberately different sensitivities:

    * The number is digits, and the signed `reference_id` opens with the last
      four of them. Comparing four digits against four digits is reliable
      enough to accuse on, so a mismatch is fatal.
    * The name is OCR'd prose, where scan noise routinely mangles a character
      or two. Flagging on any difference would wrongly accuse honest people
      with imperfect scans, so this only fires on gross dissimilarity.
    """
    codes: list[str] = []

    reference_id = str(qr_result.fields.get("reference_id", "") or "")
    signed_last_four = reference_id[:4]

    if signed_last_four.isdigit() and text_result.aadhaar_numbers:
        printed_number = text_result.aadhaar_numbers[0]
        if printed_number[-4:] == signed_last_four:
            codes.append("OCR_QR_NUMBER_MATCHES")
        else:
            codes.append("OCR_QR_NUMBER_MISMATCH")

    signed_name = str(qr_result.fields.get("name", "") or "")
    printed_text = getattr(text_result, "text", "") or ""
    if signed_name and printed_text:
        def _letters(value: str) -> str:
            return "".join(ch for ch in value.upper() if ch.isalpha())

        target = _letters(signed_name)
        haystack = _letters(printed_text)
        if len(target) >= 6 and haystack:
            # Best alignment of the signed name anywhere in the OCR'd text.
            best = SequenceMatcher(None, target, haystack).find_longest_match(
                0, len(target), 0, len(haystack)
            )
            coverage = best.size / len(target)
            # 0.6 is loose on purpose. Below it, the signed name is essentially
            # absent from the printed card rather than merely misread.
            if coverage < 0.6:
                codes.append("OCR_QR_NAME_MISMATCH")

    return codes


# ---------------------------------------------------------------------------
# Aadhaar
# ---------------------------------------------------------------------------

def verify_upload_qr(original: bytes, rendered: bytes):
    """Read PDF-embedded QR pixels before page rendering can downsample them."""
    if original.startswith(b"%PDF-"):
        from pyzbar.pyzbar import decode
        with pymupdf.open(stream=original, filetype="pdf") as pdf:
            seen = set()
            for item in pdf[0].get_images(full=True)[:32]:
                xref, width, height = item[0], item[2], item[3]
                if xref in seen or min(width, height) < 80 or width * height > settings.max_image_pixels:
                    continue
                seen.add(xref)
                if not 0.7 <= width / height <= 1.4:
                    continue
                image_data = pdf.extract_image(xref)["image"]
                with Image.open(io.BytesIO(image_data)) as image:
                    payloads = decode(image)
                for symbol in payloads:
                    try:
                        return aadhaar_qr.parse_payload(symbol.data.decode("utf-8"), UIDAI_KEY)
                    except (aadhaar_qr.QRDecodeError, UnicodeDecodeError):
                        continue
    return aadhaar_qr.verify_aadhaar_image(rendered, UIDAI_KEY)

@app.post("/verify/aadhaar")
async def verify_aadhaar(
    document: UploadFile = File(...),
    back_document: UploadFile | None = File(None),
):
    """
    Aadhaar layout handling:
      - New format: photo/front and Secure QR/back are uploaded separately.
      - Legacy format: photo + QR may be on the same side; one upload still works.

    `document` is the FRONT image. If `back_document` is supplied, QR scanning
    is performed on the back first and falls back to the front for legacy cards.
    """
    front_original = await read_upload(document)
    back_original = await read_upload(back_document) if back_document else None
    front_bytes = rasterise_if_pdf(front_original, document.content_type)
    back_bytes = (
        rasterise_if_pdf(back_original, back_document.content_type)
        if back_original is not None and back_document else None
    )

    qr_source = back_bytes if back_bytes is not None else front_bytes
    qr_result = verify_upload_qr(back_original if back_original is not None else front_original, qr_source)

    # If a back image was supplied but no QR was found there, fall back to the
    # front. This keeps the endpoint tolerant of users uploading the wrong side
    # first while still supporting the new two-sided layout.
    if back_bytes is not None and qr_result.version == "UNKNOWN":
        front_qr_result = verify_upload_qr(front_original, front_bytes)
        if front_qr_result.version != "UNKNOWN":
            qr_result = front_qr_result

    image_bytes = front_bytes
    codes = list(qr_result.reasons)

    # The reference_id in a signed payload holds the last four digits, which is
    # not enough to run Verhoeff. Fall back to OCR for the full number so the
    # checksum is still demonstrable, and note where the number came from.
    text_result = ocr.extract_text(image_bytes)
    number_source = None
    if text_result.aadhaar_numbers:
        number_source = "ocr"
        # The pass/fail is carried entirely by which reason code comes back
        # (AADHAAR_VERHOEFF_OK vs one of the failure codes), which assess()
        # tiers correctly. Named `_` so a later edit does not assume the
        # boolean gates something it does not.
        _, reason = verhoeff.validate_aadhaar_number(text_result.aadhaar_numbers[0])
        codes.append(reason)

    # Does the printed side agree with the signed payload?
    codes.extend(crosscheck_printed_against_signed(qr_result, text_result))

    ela_result = ela.analyse(image_bytes)
    codes.extend(ela_result.reasons)

    # Independent forensic signals, all heuristic tier. None can decide a
    # verdict alone; assess() needs two before it will even ask for a human.
    forensic = forensics.analyse_all(image_bytes)
    codes.extend(forensic["reasons"])

    assessment = assess(codes)
    record_id = store.record(
        doc_type="aadhaar",
        verdict=assessment.verdict.value,
        decided_by=assessment.decided_by.value if assessment.decided_by else None,
        binding=assessment.identity_binding.value,
        reason_codes=[item["code"] for item in assessment.reasons],
        advisory_codes=[item["code"] for item in assessment.advisory],
        qr_version=qr_result.version,
    )

    return envelope(
        assessment,
        {
            "qr_version": qr_result.version,
            "signature_verified": qr_result.signature_verified,
            "layout": "two_sided_new" if back_bytes is not None else "legacy_or_single_image",
            "qr_side": "back" if back_bytes is not None else "uploaded_document",
            "photo_side": "front",
            "fields": qr_result.redacted() if settings.redact_identifiers else qr_result.fields,
            "id_photo_available": qr_result.photo_jp2 is not None,
            "aadhaar_number_source": number_source,
            "ocr_engine": text_result.engine,
            "forensics": forensic,
            # Built from the measurements above, so every pixel corresponds
            # to something real. ELA's own heatmap only exists for JPEGs
            # that kept an editing history, which is almost never the
            # case here, so the UI had nothing to show without these.
            "maps": forensics.render_maps(image_bytes),
            "ela": {
                "applicable": ela_result.applicable,
                "flagged_blocks": ela_result.flagged_blocks,
                "flagged_fraction": round(ela_result.flagged_fraction, 4),
                "heatmap_png_base64": ela_result.heatmap_png_base64,
            },
        },
        record_id,
    )


@app.post("/verify/aadhaar-full")
async def verify_aadhaar_full(
    document: UploadFile = File(...),
    frames: list[UploadFile] = File(...),
    consent_subject: str = Form(...),
    back_document: UploadFile | None = File(None),
    challenge: Literal["blink", "head_turn"] = Form("blink"),
):
    """
    The demo centrepiece: authenticity and identity binding in one call.

    Current two-sided Aadhaar handling:
      - FRONT: printed photograph.
      - BACK: QR code.
    The QR is still verified from the signed payload, while the live face is
    compared with the printed photograph on the FRONT when a back image is
    supplied. Legacy one-sided cards remain supported, and their signed QR
    photo is used when available.
    """
    consent_gate(consent_subject)

    # `document` is always the FRONT side.
    # `back_document` is optional and should contain the BACK side for the
    # current two-sided Aadhaar layout. Legacy cards can still be verified with
    # only `document`.
    front_original = await read_upload(document)
    back_original = await read_upload(back_document) if back_document else None
    front_bytes = rasterise_if_pdf(front_original, document.content_type)
    back_bytes = (
        rasterise_if_pdf(back_original, back_document.content_type)
        if back_original is not None and back_document else None
    )
    frame_bytes = await read_live_frames(frames)

    qr_source = back_bytes if back_bytes is not None else front_bytes
    qr_result = verify_upload_qr(back_original if back_original is not None else front_original, qr_source)

    # Tolerate an incorrectly supplied side and preserve legacy support.
    if back_bytes is not None and qr_result.version == "UNKNOWN":
        front_qr_result = verify_upload_qr(front_original, front_bytes)
        if front_qr_result.version != "UNKNOWN":
            qr_result = front_qr_result

    codes = list(qr_result.reasons)

    # Which photograph do we trust?
    #
    # Always the one sealed inside the signature, whenever it exists. The
    # printed front is unsigned: a forger reprints it freely, so matching a
    # live selfie against it proves only that the forger printed their own
    # face. Matching against the signed copy is what binds a person to the
    # credential UIDAI actually issued.
    #
    # This used to prefer `front_bytes` whenever a back image was supplied,
    # which meant the documented two-sided path — the normal one — accepted a
    # genuine QR transplanted onto someone else's card.
    if qr_result.photo_jp2 is not None:
        face_source = qr_result.photo_jp2
        face_source_label = "signed_qr_photo"
    else:
        # Legacy and V1 cards carry no signed photograph. Fall back to the
        # printed one, and label it so the response never implies the binding
        # is as strong as it is on a Secure QR.
        face_source = front_bytes
        face_source_label = "printed_front_unsigned"

    # Transplant check: does the face printed on the card match the face sealed
    # inside that card's own QR? They should be the same person. If they are
    # not, the QR came from somewhere else — which is exactly the attack a
    # valid signature cannot detect on its own.
    if qr_result.photo_jp2 is not None and back_bytes is not None:
        printed_vs_signed = face_match.compare_faces(qr_result.photo_jp2, front_bytes)
        if printed_vs_signed.compared:
            codes.append(
                "QR_PHOTO_MATCHES_PRINTED" if printed_vs_signed.is_match
                else "QR_PHOTO_MISMATCH_PRINTED"
            )
        else:
            # No usable face on one side or the other. Say so rather than
            # silently treating an unperformed check as a pass.
            codes.append("QR_PHOTO_COMPARE_UNAVAILABLE")

    liveness = face_match.check_liveness(list(frame_bytes), challenge=challenge)
    codes.extend(liveness.reasons)

    match = face_match.compare_faces(
        face_source,
        frame_bytes[len(frame_bytes) // 2],
    )
    codes.extend(match.reasons)

    ela_result = ela.analyse(front_bytes)
    codes.extend(ela_result.reasons)

    forensic = forensics.analyse_all(front_bytes)
    codes.extend(forensic["reasons"])

    # Read the printed side and check it against the signed fields, same as the
    # QR-only endpoint. Without this, a transplanted QR is caught by the photo
    # comparison alone; with it, an altered number or name is caught too.
    text_result = ocr.extract_text(front_bytes)
    codes.extend(crosscheck_printed_against_signed(qr_result, text_result))

    assessment = assess(
        codes,
        face_matched=match.is_match,
        liveness_passed=liveness.passed,
        identity_attempted=True,
    )
    record_id = store.record(
        doc_type="aadhaar",
        verdict=assessment.verdict.value,
        decided_by=assessment.decided_by.value if assessment.decided_by else None,
        binding=assessment.identity_binding.value,
        reason_codes=[item["code"] for item in assessment.reasons],
        advisory_codes=[item["code"] for item in assessment.advisory],
        qr_version=qr_result.version,
        face_distance=match.distance,
        liveness=liveness.challenge if liveness.checked else None,
    )

    # Frames and the extracted photo go out of scope here and are never
    # written anywhere. Nothing biometric reaches the response or the store.
    return envelope(
        assessment,
        {
            "qr_version": qr_result.version,
            "signature_verified": qr_result.signature_verified,
            "layout": "two_sided_new" if back_bytes is not None else "legacy_or_single_image",
            "qr_side": "back" if back_bytes is not None else "uploaded_document",
            "photo_side": "front",
            "face_source": face_source_label,
            "signed_photo_available": qr_result.photo_jp2 is not None,
            "fields": qr_result.redacted() if settings.redact_identifiers else qr_result.fields,
            "face": {
                "compared": match.compared,
                "distance": match.distance,
                "similarity": match.similarity,
                "threshold": match.threshold,
                "model": match.model,
                "is_match": match.is_match,
            },
            "liveness": {
                "checked": liveness.checked,
                "passed": liveness.passed,
                "challenge": liveness.challenge,
                "detail": liveness.detail,
            },
            "forensics": forensic,
            # Built from the measurements above, so every pixel corresponds
            # to something real. ELA's own heatmap only exists for JPEGs
            # that kept an editing history, which is almost never the
            # case here, so the UI had nothing to show without these.
            "maps": forensics.render_maps(front_bytes),
            "ela": {
                "applicable": ela_result.applicable,
                "flagged_fraction": round(ela_result.flagged_fraction, 4),
            },
        },
        record_id,
    )


# ---------------------------------------------------------------------------
# PAN
# ---------------------------------------------------------------------------

@app.post("/verify/pan")
async def verify_pan(
    document: UploadFile = File(...),
    pan_number: str | None = Form(None),
):
    image_bytes = rasterise_if_pdf(
        await read_upload(document), document.content_type
    )
    text_result = ocr.extract_text(image_bytes, pan_mode=True)

    candidate = pan_number or (text_result.pan_numbers[0] if text_result.pan_numbers else "")
    pan_report = pan.validate_pan(candidate)
    codes = list(pan_report["reasons"])

    name_check = pan.cross_check_name(candidate, text_result.text)
    codes.extend(name_check["reasons"])

    ela_result = ela.analyse(image_bytes)
    codes.extend(ela_result.reasons)

    # Independent forensic signals, all heuristic tier. None can decide a
    # verdict alone; assess() needs two before it will even ask for a human.
    forensic = forensics.analyse_all(image_bytes)
    codes.extend(forensic["reasons"])

    assessment = assess(codes)
    record_id = store.record(
        doc_type="pan",
        verdict=assessment.verdict.value,
        decided_by=assessment.decided_by.value if assessment.decided_by else None,
        binding=assessment.identity_binding.value,
        reason_codes=[item["code"] for item in assessment.reasons],
        advisory_codes=[item["code"] for item in assessment.advisory],
    )

    return envelope(
        assessment,
        {
            "pan": pan_report,
            "name_cross_check": name_check,
            "ocr_engine": text_result.engine,
            "forensics": forensic,
            # Built from the measurements above, so every pixel corresponds
            # to something real. ELA's own heatmap only exists for JPEGs
            # that kept an editing history, which is almost never the
            # case here, so the UI had nothing to show without these.
            "maps": forensics.render_maps(image_bytes),
            "ela": {
                "applicable": ela_result.applicable,
                "flagged_blocks": ela_result.flagged_blocks,
                "heatmap_png_base64": ela_result.heatmap_png_base64,
            },
            "note": (
                "PAN has no offline cryptographic material and no public check "
                "digit. A clean result here means the structure is plausible, "
                "nothing more."
            ),
        },
        record_id,
    )



# ---------------------------------------------------------------------------
# Passport
# ---------------------------------------------------------------------------

@app.post("/verify/passport")
async def verify_passport(document: UploadFile = File(...)):
    """
    Validate a passport's machine-readable zone.

    Unlike PAN or a marksheet, a passport carries real check digits: ICAO 9303
    defines checksums over the passport number, date of birth, expiry, and a
    composite of all three. That makes this a STRUCTURAL check in the same
    class as the Verhoeff digit on an Aadhaar number -- deterministic
    arithmetic, so an altered field is caught by the maths rather than by a
    heuristic guess.

    It still cannot reach GENUINE_SIGNED. Check digits are public arithmetic
    and a forger recomputes them; the real cryptographic anchor is the eMRTD
    chip, which is signed by the issuing state and unreachable from a
    photograph. So a clean MRZ means "internally consistent" and the ceiling
    stays UNVERIFIABLE, which is the honest answer.
    """
    image_bytes = rasterise_if_pdf(
        await read_upload(document), document.content_type
    )

    text_result = ocr.extract_text(image_bytes)
    mrz = passport.parse(text_result.text)
    codes = list(mrz.reasons)

    ela_result = ela.analyse(image_bytes)
    codes.extend(ela_result.reasons)

    forensic = forensics.analyse_all(image_bytes)
    codes.extend(forensic["reasons"])

    assessment = assess(codes)
    record_id = store.record(
        doc_type="passport",
        verdict=assessment.verdict.value,
        decided_by=assessment.decided_by.value if assessment.decided_by else None,
        binding=assessment.identity_binding.value,
        reason_codes=[item["code"] for item in assessment.reasons],
        advisory_codes=[item["code"] for item in assessment.advisory],
    )

    return envelope(
        assessment,
        {
            "mrz_found": mrz.found,
            "mrz": mrz.redacted() if mrz.found else None,
            "ocr_engine": text_result.engine,
            "forensics": forensic,
            "maps": forensics.render_maps(image_bytes),
            "ela": {
                "applicable": ela_result.applicable,
                "flagged_fraction": round(ela_result.flagged_fraction, 4),
            },
        },
        record_id,
    )

# ---------------------------------------------------------------------------
# Marksheet
# ---------------------------------------------------------------------------

@app.post("/verify/marksheet")
async def verify_marksheet(
    document: UploadFile = File(...),
    subject1: str = Form(...),
    subject2: str = Form(...),
    subject3: str = Form(...),
    subject4: str = Form(...),
    subject5: str = Form(...),
):
    image_bytes = rasterise_if_pdf(
        await read_upload(document), document.content_type
    )

    text_result = ocr.extract_text(
        image_bytes
    )

    selected_subjects = [
        subject1,
        subject2,
        subject3,
        subject4,
        subject5,
    ]

    sheet = marksheet.analyse(
        text_result.text,
        image_bytes,
        selected_subjects=selected_subjects,
    )

    codes = list(sheet.reasons)

    ela_result = ela.analyse(
        image_bytes
    )

    codes.extend(
        ela_result.reasons
    )

    forensic = forensics.analyse_all(image_bytes)
    codes.extend(forensic["reasons"])

    assessment = assess(codes)

    record_id = store.record(
        doc_type="marksheet",
        verdict=assessment.verdict.value,
        decided_by=(
            assessment.decided_by.value
            if assessment.decided_by
            else None
        ),
        binding=assessment.identity_binding.value,
        reason_codes=[
            item["code"]
            for item in assessment.reasons
        ],
        advisory_codes=[
            item["code"]
            for item in assessment.advisory
        ],
    )

    return envelope(
        assessment,
        {
            "selected_subjects": sheet.selected_subjects,

            "subjects": sheet.subjects,

            "selected_total": sheet.selected_total,

            "selected_maximum": sheet.selected_maximum,

            "selected_percentage": sheet.selected_percentage,

            "computed_total": sheet.computed_total,

            "printed_total": sheet.printed_total,

            "printed_percentage": sheet.printed_percentage,

            "baseline_outlier_rows": (
                sheet.baseline_outliers
            ),

            "ocr_engine": text_result.engine,

            "forensics": forensic,

            # Built from the measurements above, so every pixel corresponds

            # to something real. ELA's own heatmap only exists for JPEGs

            # that kept an editing history, which is almost never the

            # case here, so the UI had nothing to show without these.

            "maps": forensics.render_maps(image_bytes),

            "ela": {
                "applicable": ela_result.applicable,
                "flagged_blocks": (
                    ela_result.flagged_blocks
                ),
                "heatmap_png_base64": (
                    ela_result.heatmap_png_base64
                ),
            },

            "calculation_note": (
                "Only the five subjects selected by the "
                "user are included in the total and percentage. "
                "Additional subjects are excluded."
            ),
        },
        record_id,
    )


# ---------------------------------------------------------------------------
# Standalone face match
# ---------------------------------------------------------------------------

@app.post("/verify/face")
async def verify_face(
    id_photo: UploadFile = File(...),
    frames: list[UploadFile] = File(...),
    consent_subject: str = Form(...),
    challenge: Literal["blink", "head_turn"] = Form("blink"),
):
    consent_gate(consent_subject)

    id_bytes = validate_image_upload(await read_upload(id_photo))
    frame_bytes = await read_live_frames(frames)

    liveness = face_match.check_liveness(list(frame_bytes), challenge=challenge)
    match = face_match.compare_faces(id_bytes, frame_bytes[len(frame_bytes) // 2])

    codes = liveness.reasons + match.reasons
    assessment = assess(
        codes,
        face_matched=match.is_match,
        liveness_passed=liveness.passed,
        identity_attempted=True,
    )
    record_id = store.record(
        doc_type="face",
        verdict=assessment.verdict.value,
        decided_by=assessment.decided_by.value if assessment.decided_by else None,
        binding=assessment.identity_binding.value,
        reason_codes=[item["code"] for item in assessment.reasons],
        advisory_codes=[item["code"] for item in assessment.advisory],
        face_distance=match.distance,
        liveness=liveness.challenge if liveness.checked else None,
    )

    return envelope(
        assessment,
        {
            "face": {
                "compared": match.compared,
                "distance": match.distance,
                "similarity": match.similarity,
                "threshold": match.threshold,
                "model": match.model,
                "is_match": match.is_match,
            },
            "liveness": {
                "checked": liveness.checked,
                "passed": liveness.passed,
                "challenge": liveness.challenge,
                "detail": liveness.detail,
            },
        },
        record_id,
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard/history")
def dashboard_history(limit: int = Query(50, ge=1, le=100)):
    return {"records": store.history(limit), "disclaimer": DISCLAIMER}


@app.get("/dashboard/summary")
def dashboard_summary():
    return {**store.summary(), "disclaimer": DISCLAIMER}


@app.get("/reasons")
def reasons():
    return {"reasons": REASON_TEXT}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uidai_certificate_loaded": UIDAI_KEY is not None,
        "uidai_certificate_fingerprint": UIDAI_CERT_FINGERPRINT,
        "uidai_certificate_pinned": bool(settings.uidai_cert_fingerprint),
        "consent_enforcement": settings.require_consent_subject,
        "consent_subjects_configured": len(settings.consent_subjects),
    }
