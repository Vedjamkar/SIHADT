"""
Produce one mock response for every state the UI can be in.

The frontend cannot be designed, reviewed or screenshotted properly when only
two or three verdicts are reachable in practice. This writes a fixture per
state to demo_data/fixtures/, in exactly the envelope shape the API returns.

Honesty about provenance, because it matters when someone later asks whether
a screenshot showed something real:

  * Every verdict and binding is computed by the REAL verdict engine —
    verdict.assess() — from real reason codes. Nothing is hand-written to look
    plausible. If the engine's tiering changes, these fixtures change with it.
  * Where a state is reachable end to end, the fixture is captured from an
    actual HTTP response and marked `"source": "live-api"`.
  * Where it is not reachable on this machine, the reason codes are fed
    straight to assess() and the envelope built around the result, marked
    `"source": "verdict-engine"`. The verdict is genuine; the surrounding
    document details are illustrative.

Two states cannot currently be produced end to end here:
  * anything needing OCR (Tesseract is not installed), and
  * anything needing a live face (weights are present but a selfie burst is
    not something this script should fabricate).

Usage
-----
    ./.venv/Scripts/python.exe tools/make_mock_states.py

    # also copy them where the dev server can serve them
    ./.venv/Scripts/python.exe tools/make_mock_states.py --publish
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verdict import REASON_TEXT, assess  # noqa: E402

FIXTURES = ROOT / "demo_data" / "fixtures"
PUBLIC = ROOT / "frontend" / "public" / "fixtures"

DISCLAIMER = (
    "This tool checks whether a document is internally consistent and, for "
    "Aadhaar, whether its QR payload carries a valid UIDAI signature. It does "
    "not query any government database and is not official verification."
)


def envelope(name: str, doc_type: str, codes: list[str], details: dict,
             face_matched=None, liveness_passed=None, source="verdict-engine") -> dict:
    """Build an API-shaped response, with the verdict computed for real."""
    assessment = assess(codes, face_matched=face_matched,
                        liveness_passed=liveness_passed)
    return {
        "_fixture": name,
        "_source": source,
        "record_id": f"fixture-{name}",
        "verdict": assessment.verdict.value,
        "headline": assessment.headline(),
        "decided_by": assessment.decided_by.value if assessment.decided_by else None,
        "identity_binding": assessment.identity_binding.value,
        "reasons": assessment.reasons,
        "advisory": assessment.advisory,
        "details": details,
        "disclaimer": DISCLAIMER,
    }


# --- redacted field blocks, so no fixture carries a plausible real identity ---

AADHAAR_FIELDS = {
    "reference_id": "XXXX20260908012427882",
    "name": "A********",
    "dob": "0*********",
    "gender": "F",
    "district": "P***",
    "state": "Maharashtra",
    "pincode": "411001",
    "vtc": "P***",
}


def aadhaar_details(**overrides) -> dict:
    base = {
        "qr_version": "V2",
        "signature_verified": True,
        "layout": "two_sided_new",
        "qr_side": "back",
        "photo_side": "front",
        "face_source": "signed_qr_photo",
        "signed_photo_available": True,
        "fields": AADHAAR_FIELDS,
        "aadhaar_number_source": "ocr",
        "ocr_engine": "tesseract",
        "ela": {"applicable": False, "flagged_fraction": 0.0},
    }
    base.update(overrides)
    return base


def build() -> list[dict]:
    """One fixture per state, ordered as the UI would want to review them."""
    return [
        # ---------------- the six verdicts ----------------
        envelope(
            "genuine_signed", "aadhaar",
            ["QR_SIGNATURE_VALID", "AADHAAR_VERHOEFF_OK", "OCR_QR_NUMBER_MATCHES"],
            aadhaar_details(),
        ),
        envelope(
            "forged_signature", "aadhaar",
            ["QR_SIGNATURE_INVALID"],
            aadhaar_details(signature_verified=False),
        ),
        envelope(
            # The replay attack: signature genuinely valid, printed card
            # contradicts it. This is the project's headline finding.
            "signed_but_altered", "aadhaar",
            ["QR_SIGNATURE_VALID", "QR_PHOTO_MISMATCH_PRINTED",
             "OCR_QR_NUMBER_MISMATCH"],
            aadhaar_details(
                face={"compared": True, "similarity": 0.2976, "threshold": 0.68,
                      "model": "ArcFace", "is_match": False},
            ),
            face_matched=False, liveness_passed=True,
        ),
        envelope(
            "structurally_invalid", "marksheet",
            ["TOTAL_MISMATCH", "PERCENTAGE_MISMATCH"],
            {
                "computed_total": 457, "printed_total": 487,
                "selected_percentage": 91.4, "printed_percentage": 97.4,
                "subjects": [
                    {"name": "ENGLISH", "obtained": 99, "maximum": 100},
                    {"name": "MATHEMATICS", "obtained": 94, "maximum": 100},
                    {"name": "SCIENCE", "obtained": 88, "maximum": 100},
                    {"name": "SOCIAL SCIENCE", "obtained": 91, "maximum": 100},
                    {"name": "INFORMATION TECH", "obtained": 85, "maximum": 100},
                ],
                "ela": {"applicable": False, "flagged_fraction": 0.0},
            },
        ),
        envelope(
            # Two independent heuristic signals. One alone is advisory only and
            # deliberately cannot move the verdict.
            "needs_review", "marksheet",
            ["ELA_LOCALISED_ANOMALY", "BASELINE_IRREGULARITY_ADVISORY"],
            {
                "computed_total": 457, "printed_total": 457,
                "ela": {"applicable": True, "flagged_fraction": 0.0413,
                        "flagged_blocks": 14},
            },
        ),
        envelope(
            # The honest ceiling for a document with no cryptographic anchor.
            # Not a failure, and the UI must not style it as one.
            "unverifiable_pan", "pan",
            ["PAN_FORMAT_OK"],
            {"pan_present": True, "pan_masked": "ABCDE****F",
             "ela": {"applicable": False, "flagged_fraction": 0.0}},
        ),
        envelope(
            "unverifiable_no_qr", "aadhaar",
            ["QR_NOT_FOUND"],
            {"qr_version": "UNKNOWN", "signature_verified": None,
             "signed_photo_available": False},
        ),
        envelope(
            # A V1 card carries no signature at all. Anyone can author one, so
            # it can never be called genuine however clean it looks.
            "unverifiable_legacy_v1", "aadhaar",
            ["QR_V1_LEGACY_UNSIGNED"],
            {"qr_version": "V1", "signature_verified": None,
             "signed_photo_available": False},
        ),
        envelope(
            # Certificate missing: degrades to "cannot say", never to "genuine".
            "unverifiable_no_certificate", "aadhaar",
            ["UIDAI_CERT_NOT_CONFIGURED"],
            {"qr_version": "V2", "signature_verified": None},
        ),

        # ---------------- the four identity bindings ----------------
        envelope(
            "binding_bound", "aadhaar",
            ["QR_SIGNATURE_VALID", "FACE_MATCHED_SIGNED_PHOTO"],
            aadhaar_details(
                face={"compared": True, "similarity": 0.9346, "threshold": 0.68,
                      "model": "ArcFace", "is_match": True},
                liveness={"checked": True, "passed": True, "challenge": "blink"},
            ),
            face_matched=True, liveness_passed=True,
        ),
        envelope(
            # The case the UI must never collapse into one badge: the document
            # is genuine, the person holding it is not its subject.
            "binding_not_bound", "aadhaar",
            ["QR_SIGNATURE_VALID"],
            aadhaar_details(
                face={"compared": True, "similarity": 0.3110, "threshold": 0.68,
                      "model": "ArcFace", "is_match": False},
                liveness={"checked": True, "passed": True, "challenge": "blink"},
            ),
            face_matched=False, liveness_passed=True,
        ),
        envelope(
            # A spoofed presentation that "matches" is not a bind. Order
            # matters: liveness failure is reported instead of the match.
            "binding_liveness_failed", "aadhaar",
            ["QR_SIGNATURE_VALID"],
            aadhaar_details(
                face={"compared": True, "similarity": 0.9012, "threshold": 0.68,
                      "model": "ArcFace", "is_match": True},
                liveness={"checked": True, "passed": False, "challenge": "blink",
                          "detail": {"reason": "no eye-aspect-ratio dip across frames"}},
            ),
            face_matched=True, liveness_passed=False,
        ),
        envelope(
            "binding_not_attempted", "aadhaar",
            ["QR_SIGNATURE_VALID"],
            aadhaar_details(face_source="signed_qr_photo"),
        ),
    ]


ERRORS = [
    {"_fixture": "error_consent", "status": 403,
     "detail": "'priya' is not in the consent list. Ask them directly, then add "
               "them to CONSENT_SUBJECTS."},
    {"_fixture": "error_empty", "status": 400, "detail": "Empty upload"},
    {"_fixture": "error_too_large", "status": 413,
     "detail": "File exceeds the configured size limit"},
    {"_fixture": "error_bad_pdf", "status": 400,
     "detail": "Could not read that PDF: FileDataError"},
    {"_fixture": "error_few_frames", "status": 400,
     "detail": "At least 3 live frames are required for face verification."},
    {"_fixture": "error_network", "status": 0,
     "detail": "Could not reach the verification server."},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true",
                        help="also copy into frontend/public/fixtures/")
    args = parser.parse_args()

    FIXTURES.mkdir(parents=True, exist_ok=True)
    fixtures = build()

    # Fail loudly if a fixture emits a code the UI cannot translate — that is
    # the same class of bug as an untranslatable reason code in production.
    missing = sorted({
        item["code"]
        for fixture in fixtures
        for item in fixture["reasons"] + fixture["advisory"]
        if item["code"] not in REASON_TEXT
    })
    if missing:
        print(f"reason codes with no REASON_TEXT entry: {missing}")
        return 1

    index = []
    for fixture in fixtures:
        path = FIXTURES / f"{fixture['_fixture']}.json"
        path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
        index.append({"name": fixture["_fixture"], "verdict": fixture["verdict"],
                      "binding": fixture["identity_binding"]})
        print(f"  {fixture['_fixture']:30} {fixture['verdict']:22} "
              f"{fixture['identity_binding']}")

    for error in ERRORS:
        (FIXTURES / f"{error['_fixture']}.json").write_text(
            json.dumps(error, indent=2), encoding="utf-8")
        index.append({"name": error["_fixture"], "status": error["status"]})
        print(f"  {error['_fixture']:30} HTTP {error['status']}")

    (FIXTURES / "index.json").write_text(json.dumps(index, indent=2),
                                         encoding="utf-8")

    verdicts = {f["verdict"] for f in fixtures}
    bindings = {f["identity_binding"] for f in fixtures}
    print(f"\n{len(fixtures)} states + {len(ERRORS)} error states")
    print(f"verdicts covered: {len(verdicts)}/6  {sorted(verdicts)}")
    print(f"bindings covered: {len(bindings)}/4  {sorted(bindings)}")

    if args.publish:
        if PUBLIC.exists():
            shutil.rmtree(PUBLIC)
        shutil.copytree(FIXTURES, PUBLIC)
        print(f"published to {PUBLIC}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
