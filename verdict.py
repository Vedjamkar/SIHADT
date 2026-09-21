"""
Verdict engine.

This is the part of your plan I changed, so here is the argument.

Your table lists seven checks feeding one verified/flagged verdict. If those
get averaged or weighted into a score, two bad things happen. First, a genuine
document photographed badly picks up ELA noise and gets marked down despite
carrying a valid UIDAI signature, which is a mathematical proof of issuance.
Second, and worse, a forged document that happens to have a clean compression
history gains points it did not earn. A proof and a heuristic do not belong in
the same arithmetic.

So checks are sorted into tiers and the strongest available tier decides.

    Tier 1  CRYPTOGRAPHIC   UIDAI QR signature.
                            Binary, authoritative. If present it decides,
                            full stop. Nothing in Tier 2 or 3 can overturn it
                            in either direction.
    Tier 2  STRUCTURAL      Verhoeff, PAN pattern, marksheet arithmetic,
                            field cross-consistency.
                            Cheap to forge, so a pass means little, but a
                            failure is a hard, explainable flag.
    Tier 3  HEURISTIC       ELA, baseline alignment.
                            Advisory only. Never the sole cause of a flag.
                            Surfaced to a human reviewer with a heatmap.

And the verdict vocabulary is deliberately not "verified/flagged", because for
PAN and marksheets you have no authoritative source and "verified" would be a
false claim. Five outcomes:

    GENUINE_SIGNED       Tier 1 passed. Issuer-signed data, unaltered.
    FORGED_SIGNATURE     Tier 1 failed. The strongest claim you can make.
    STRUCTURALLY_INVALID Tier 2 failed. Explainable, document-specific.
    UNVERIFIABLE         No Tier 1 available and Tier 2 clean. This is the
                         honest answer for every PAN and every marksheet.
                         It is not a pass.
    NEEDS_REVIEW         Tier 3 raised something on an otherwise clean doc.

Note that GENUINE_SIGNED still does not mean "this person is who they say".
Document authenticity and identity binding are separate axes, and
`identity_binding` below reports the second one independently. Keep them
separate in the UI too. Collapsing them is how the "forger copies a real QR"
question sinks a demo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    CRYPTOGRAPHIC = "cryptographic"
    STRUCTURAL = "structural"
    HEURISTIC = "heuristic"


class Verdict(str, Enum):
    GENUINE_SIGNED = "GENUINE_SIGNED"
    FORGED_SIGNATURE = "FORGED_SIGNATURE"
    # A genuinely issuer-signed QR sitting on a card whose printed side
    # contradicts it. The signature is real; the paper around it is not the
    # paper it was issued for. This is the transplanted-QR forgery, and it
    # needs its own verdict because calling it FORGED_SIGNATURE would be false
    # and calling it GENUINE_SIGNED would be dangerous.
    SIGNED_BUT_ALTERED = "SIGNED_BUT_ALTERED"
    STRUCTURALLY_INVALID = "STRUCTURALLY_INVALID"
    UNVERIFIABLE = "UNVERIFIABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Binding(str, Enum):
    BOUND = "BOUND"                  # live face matched the ID photo, liveness ok
    NOT_BOUND = "NOT_BOUND"          # face did not match
    LIVENESS_FAILED = "LIVENESS_FAILED"
    CHECK_FAILED = "CHECK_FAILED"    # attempted, but a backend/check produced no result
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


# Human-readable text for every reason code the services can emit. The
# dashboard should render these rather than raw codes, and any code missing
# from this map is a bug worth failing loudly on in tests.
REASON_TEXT: dict[str, str] = {
    "QR_SIGNATURE_VALID": "UIDAI digital signature verified. Field data is issuer-signed and unaltered.",
    "QR_SIGNATURE_INVALID": "UIDAI digital signature did not verify. Data was altered after issuance, or the QR was fabricated.",
    "QR_V1_LEGACY_UNSIGNED": "Legacy V1 QR code carries no signature and cannot be verified.",
    "QR_NOT_FOUND": "A QR code could not be read from this image. A visible code may need a clearer or original-resolution upload.",
    "QR_DECODE_FAILED": "QR code found but its payload did not match any known Aadhaar format.",
    "UIDAI_CERT_NOT_CONFIGURED": "UIDAI public certificate not loaded, so signature checking was skipped.",
    "QR_PHOTO_MATCHES_PRINTED": "The photograph printed on the card matches the one sealed inside the signed QR.",
    "QR_PHOTO_MISMATCH_PRINTED": "The photograph printed on the card does NOT match the one sealed inside the signed QR. The QR appears to have been taken from a different card.",
    "QR_PHOTO_COMPARE_UNAVAILABLE": "Could not compare the printed photograph against the signed one; face comparison was unavailable.",
    "OCR_QR_NUMBER_MATCHES": "The Aadhaar number printed on the card agrees with the signed QR payload.",
    "OCR_QR_NUMBER_MISMATCH": "The Aadhaar number printed on the card disagrees with the signed QR payload. The printed side has been altered, or the QR belongs to someone else.",
    "OCR_QR_NAME_MISMATCH": "The name printed on the card disagrees with the name inside the signed QR payload.",
    "FACE_MATCHED_SIGNED_PHOTO": "The live face matched the photograph sealed inside the signed QR payload.",
    "ELA_NOT_APPLICABLE_CAMERA_CAPTURE": "This image came straight from a camera, so it has a single compression history and Error Level Analysis cannot say anything about it. Photographing a printed document destroys the evidence this technique relies on.",

    # --- forensics.py: independent signals, all advisory ---
    "SCREEN_REPLAY_SUSPECTED": "The image carries interference patterns typical of a photograph taken of a screen, rather than of a physical document. Advisory only.",
    "SCREEN_REPLAY_NOT_DETECTED": "No screen-interference pattern was found. This does not rule out a screen capture.",
    "SCREEN_REPLAY_NOT_CHECKED": "The screen-interference check could not run on this file.",
    "COPY_MOVE_NOT_VALIDATED": "A duplicated-region check ran, but this detector is not yet reliable enough for its result to mean anything, so it is reported without a conclusion.",
    "COPY_MOVE_NOT_DETECTED": "No duplicated region was found within the image.",
    "COPY_MOVE_NOT_CHECKED": "The duplicated-region check could not run on this file.",
    "NOISE_INCONSISTENT": "Different areas of this image have noticeably different sensor-noise levels, which can indicate content spliced in from another source. Advisory only, and common in heavily edited or re-compressed images.",
    "NOISE_CONSISTENT": "Sensor noise is even across the image.",
    "NOISE_NOT_CHECKED": "The sensor-noise check could not run on this file.",
    "METADATA_EDITOR_PRESENT": "The file's own metadata names image-editing software. This says the file was re-saved by an editor; it does not by itself mean the document was altered.",
    "METADATA_NO_EDITOR": "File metadata names no image-editing software.",
    "METADATA_ABSENT": "The file carries no metadata. This is normal for anything sent through a messaging app and is not suspicious on its own.",
    "METADATA_NOT_CHECKED": "File metadata could not be read.",
    "AADHAAR_VERHOEFF_OK": "Aadhaar number passes the Verhoeff checksum.",
    "AADHAAR_VERHOEFF_FAILED": "Aadhaar number fails the Verhoeff checksum and cannot have been issued.",
    "AADHAAR_LENGTH_INVALID": "Aadhaar number is not 12 digits.",
    "AADHAAR_LEADING_DIGIT_INVALID": "Aadhaar numbers are not issued starting with 0 or 1.",
    "MRZ_CHECKSUMS_OK": "All machine-readable-zone check digits on this passport are internally consistent.",
    "MRZ_CHECK_DIGIT_FAILED": "A machine-readable-zone check digit does not match its field. On a passport these are arithmetic, so a mismatch means the printed data disagrees with its own checksum — either an alteration, or an OCR misread of the MRZ.",
    "MRZ_NOT_FOUND": "No machine-readable zone was found in the image. Passports carry two lines of MRZ at the foot of the data page; make sure they are in frame.",
    "MRZ_MALFORMED": "Something MRZ-shaped was found but did not parse as a known format.",
    "MRZ_DOCUMENT_EXPIRED": "The expiry date in the machine-readable zone has passed. This is a fact about the document, not a sign of forgery.",
    "PAN_FORMAT_OK": "PAN matches the expected structure.",
    "PAN_PATTERN_INVALID": "PAN does not match the five-letter, four-digit, one-letter structure.",
    "PAN_LENGTH_INVALID": "PAN is not 10 characters.",
    "PAN_HOLDER_TYPE_UNKNOWN": "Fourth character of the PAN is not a recognised holder-type code.",
    "PAN_SURNAME_INITIAL_MISMATCH": "Fifth PAN character does not match any name initial read from the card.",
    "MARKS_EXCEED_MAXIMUM": "A subject score exceeds its stated maximum.",
    "TOTAL_MISMATCH": "Subject marks do not sum to the printed total.",
    "TOTAL_CONSISTENT": "Subject marks sum to the printed total.",
    "PERCENTAGE_MISMATCH": "Printed percentage does not follow from the printed marks.",
    "PERCENTAGE_IMPOSSIBLE": "Printed percentage exceeds 100.",
    "MARKSHEET_NO_INTERNAL_INCONSISTENCY": "No internal inconsistency found. This is not board verification.",
    "BASELINE_IRREGULARITY_ADVISORY": "Some text rows sit off the common baseline. Often benign; review the highlighted rows.",
    "ELA_LOCALISED_ANOMALY": "Compression analysis shows a localised anomaly. Advisory only, and common around printed text.",
    "ELA_NO_LOCALISED_ANOMALY": "Compression analysis found no localised anomaly.",
    "ELA_NOT_APPLICABLE_NON_JPEG": "Image is not a JPEG, so compression analysis cannot be applied.",
    "FACE_MATCH": "Live face matches the photo on the document.",
    "FACE_NO_MATCH": "Live face does not match the photo on the document.",
    "FACE_NOT_DETECTED": "No face could be located in one of the images.",
    "FACE_MATCH_ERROR": "Face comparison failed to run.",
    "LIVENESS_BLINK_OK": "Blink challenge satisfied across frames.",
    "LIVENESS_BLINK_FAILED": "Blink challenge not satisfied. A still photo would fail this way.",
    "LIVENESS_HEAD_TURN_OK": "Head-turn challenge satisfied across frames.",
    "LIVENESS_HEAD_TURN_FAILED": "Head-turn challenge not satisfied.",
    "LIVENESS_FACE_NOT_TRACKED": "Face could not be tracked across enough frames.",
    "LIVENESS_INSUFFICIENT_FRAMES": "At least three frames are required for a liveness check.",
    "LIVENESS_CHALLENGE_INVALID": "Liveness challenge must be blink or head turn.",
    "LIVENESS_BACKEND_UNAVAILABLE": "Liveness backend is not installed.",
    "LIVENESS_REPLAY_ATTACK_NOT_COVERED": "This check defeats printed photos but not video replay or screen replay.",
    "AGE_GAP_LARGE": "The ID photo and the live selfie show a large apparent age gap. A weak or borderline face-match distance can be explained by this rather than by a different person. Advisory only.",
    "AGE_GAP_NORMAL": "The ID photo and the live selfie show a comparable apparent age.",
    "AGE_ESTIMATION_UNAVAILABLE": "Apparent age could not be estimated for one or both images.",
    "IDENTITY_NOT_CHECKED": "No selfie supplied, so the document was not bound to a live person.",
    "MARKSHEET_SELECTION_COUNT_INVALID":
    "Exactly five subjects must be selected.",

"SELECTED_SUBJECT_NOT_FOUND":
    "One of the selected subjects could not be reliably found in the marksheet.",

"MARKSHEET_SELECTION_OK":
    "All five selected subjects were found and included in the calculation.",
}

TIER_OF_REASON: dict[str, Tier] = {}
for _code in (
    "QR_SIGNATURE_VALID",
    "QR_SIGNATURE_INVALID",
):
    TIER_OF_REASON[_code] = Tier.CRYPTOGRAPHIC
for _code in (
    "AADHAAR_VERHOEFF_FAILED",
    "MRZ_CHECK_DIGIT_FAILED",
    "AADHAAR_LENGTH_INVALID",
    "AADHAAR_LEADING_DIGIT_INVALID",
    "PAN_PATTERN_INVALID",
    "PAN_LENGTH_INVALID",
    "PAN_HOLDER_TYPE_UNKNOWN",
    "MARKS_EXCEED_MAXIMUM",
    "TOTAL_MISMATCH",
    "PERCENTAGE_MISMATCH",
    "PERCENTAGE_IMPOSSIBLE",
    "MARKSHEET_SELECTION_COUNT_INVALID",
    "SELECTED_SUBJECT_NOT_FOUND",
):
    TIER_OF_REASON[_code] = Tier.STRUCTURAL
for _code in (
    # Each of these is a genuine but fallible signal. They are heuristic on
    # purpose: assess() will not let any single one of them move a verdict,
    # and it takes two independent signals before it will even ask for a
    # human to look. A false accusation costs an honest applicant far more
    # than a missed forgery costs us.
    "SCREEN_REPLAY_SUSPECTED",
    "NOISE_INCONSISTENT",
    "METADATA_EDITOR_PRESENT",
    "ELA_LOCALISED_ANOMALY",
    "BASELINE_IRREGULARITY_ADVISORY",
    "PAN_SURNAME_INITIAL_MISMATCH",
    "AGE_GAP_LARGE",
):
    TIER_OF_REASON[_code] = Tier.HEURISTIC

FATAL_CRYPTOGRAPHIC = {"QR_SIGNATURE_INVALID"}
PASSING_CRYPTOGRAPHIC = {"QR_SIGNATURE_VALID"}

# Evidence that a genuine, correctly-signed QR is sitting on a card that
# contradicts it — the transplanted-QR forgery. These are cryptographic-tier
# findings even though the signature itself verified, because each one is a
# direct comparison against signed bytes rather than a heuristic guess. They
# must be able to overturn GENUINE_SIGNED; that is the entire point.
FATAL_TRANSPLANT = {
    "QR_PHOTO_MISMATCH_PRINTED",
    "OCR_QR_NUMBER_MISMATCH",
    "OCR_QR_NAME_MISMATCH",
}
for _code in FATAL_TRANSPLANT:
    TIER_OF_REASON[_code] = Tier.CRYPTOGRAPHIC

FATAL_STRUCTURAL = {
    code for code, tier in TIER_OF_REASON.items() if tier is Tier.STRUCTURAL
}


@dataclass
class Assessment:
    verdict: Verdict
    identity_binding: Binding
    decided_by: Tier | None
    reasons: list[dict] = field(default_factory=list)
    advisory: list[dict] = field(default_factory=list)

    def headline(self) -> str:
        return {
            Verdict.GENUINE_SIGNED: "Issuer-signed and unaltered",
            Verdict.FORGED_SIGNATURE: "Signature check failed",
            Verdict.SIGNED_BUT_ALTERED: "Genuine QR on a card that contradicts it",
            Verdict.STRUCTURALLY_INVALID: "Structurally invalid",
            Verdict.UNVERIFIABLE: "Not independently verifiable",
            Verdict.NEEDS_REVIEW: "Needs human review",
        }[self.verdict]


def _describe(code: str) -> dict:
    return {
        "code": code,
        "tier": TIER_OF_REASON.get(code, Tier.HEURISTIC).value,
        "message": REASON_TEXT.get(code, code),
    }


def assess(
    reason_codes: list[str],
    face_matched: bool | None = None,
    liveness_passed: bool | None = None,
    identity_attempted: bool | None = None,
) -> Assessment:
    """
    Fold a flat list of reason codes into one verdict, strongest tier wins.
    """
    codes = [code for code in dict.fromkeys(reason_codes) if code]

    crypto_fail = [code for code in codes if code in FATAL_CRYPTOGRAPHIC]
    crypto_pass = [code for code in codes if code in PASSING_CRYPTOGRAPHIC]
    structural_fail = [code for code in codes if code in FATAL_STRUCTURAL]
    heuristic_flags = [
        code
        for code in codes
        if TIER_OF_REASON.get(code) is Tier.HEURISTIC
    ]

    transplant_fail = [code for code in codes if code in FATAL_TRANSPLANT]

    if crypto_fail:
        verdict, decided_by, primary = Verdict.FORGED_SIGNATURE, Tier.CRYPTOGRAPHIC, crypto_fail

    elif transplant_fail:
        # The signature verified, and the printed card still disagrees with what
        # it says. Ranked above GENUINE_SIGNED deliberately: a valid signature
        # on transplanted paper is the one case where "issuer-signed" is true
        # and dangerously misleading at the same time.
        verdict, decided_by, primary = (
            Verdict.SIGNED_BUT_ALTERED, Tier.CRYPTOGRAPHIC, transplant_fail
        )

    elif structural_fail:
        # Checked BEFORE crypto_pass, not after. The signature covers the bytes
        # inside the QR payload and nothing else, so a failure on the printed
        # side of the card — a number that fails its checksum, marks that do not
        # add up — is not overturned by it. Suppressing these under a valid
        # signature was how a transplanted QR used to pass silently.
        verdict, decided_by, primary = Verdict.STRUCTURALLY_INVALID, Tier.STRUCTURAL, structural_fail

    elif crypto_pass:
        verdict, decided_by, primary = Verdict.GENUINE_SIGNED, Tier.CRYPTOGRAPHIC, crypto_pass

    elif len(heuristic_flags) >= 2:
        # "Never the sole cause of a flag" (see the tier table above) is enforced
        # here rather than merely stated. One heuristic signal is advisory and
        # cannot move the verdict; it takes two independent ones to ask for a
        # human. ELA in particular fires readily on sharp print and ordinary
        # camera noise, and a false accusation costs an honest applicant far
        # more than a missed forgery costs us.
        verdict, decided_by, primary = Verdict.NEEDS_REVIEW, Tier.HEURISTIC, heuristic_flags

    else:
        verdict, decided_by, primary = Verdict.UNVERIFIABLE, None, []

    # Preserve the original public API for callers that supplied face/liveness
    # booleans before identity_attempted existed. Endpoints pass True explicitly
    # so a backend failure represented by two None values is still CHECK_FAILED.
    if identity_attempted is None:
        identity_attempted = face_matched is not None or liveness_passed is not None
    binding = _binding(face_matched, liveness_passed, identity_attempted)

    advisory_codes = [code for code in codes if code not in primary]
    return Assessment(
        verdict=verdict,
        identity_binding=binding,
        decided_by=decided_by,
        reasons=[_describe(code) for code in primary],
        advisory=[_describe(code) for code in advisory_codes],
    )


def _binding(
    face_matched: bool | None,
    liveness_passed: bool | None,
    identity_attempted: bool = False,
) -> Binding:
    if not identity_attempted:
        return Binding.NOT_ATTEMPTED
    if liveness_passed is False:
        # Order matters: a spoofed presentation that "matches" is not a bind.
        # Report the liveness failure rather than the match.
        return Binding.LIVENESS_FAILED
    if face_matched is False:
        return Binding.NOT_BOUND
    if face_matched is True and liveness_passed is True:
        return Binding.BOUND
    # A face result without a liveness result (or vice versa) is incomplete.
    # In particular, a successful face comparison must never become BOUND when
    # MediaPipe failed to load or could not produce a liveness result.
    return Binding.CHECK_FAILED
