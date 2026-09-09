"""
Does the face-match path survive the QR photo budget?

The replay defence compares the photograph sealed inside the signed QR against
the one printed on the card. That only works if a face is still detectable
after the payload budget has compressed it to roughly 96x96 greyscale under
1800 bytes — the size a Secure QR can actually carry.

This script answers that by running the real face_match.compare_faces on
compressed synthetic faces. Run it before trusting any replay demo:

    ./.venv/Scripts/python.exe tools/check_face_pipeline.py

Expected, if the pipeline is sound:
    compressed victim  vs full victim    -> compared=True,  match=True
    compressed victim  vs full attacker  -> compared=True,  match=False

`compared=False` on either line means the detector could not find a face at
that size, and the replay catch cannot be demonstrated until the budget or the
compression ladder in tools/mock_pki.py is loosened.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The Windows console defaults to cp1252, and DeepFace's error strings contain
# characters it cannot encode — printing a failure reason would then raise
# UnicodeEncodeError and hide the very diagnosis this script exists to report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

import face_match  # noqa: E402
import mock_pki  # noqa: E402

FACES = Path(__file__).resolve().parent.parent / "demo_data" / "faces"


def main() -> int:
    victim = FACES / "victim.jpg"
    attacker = FACES / "attacker.jpg"

    for path in (victim, attacker):
        if not path.exists():
            print(f"missing {path} — see docs/PROJECT_STATE.md task N1")
            return 2

    compressed = mock_pki._encode_photo(Image.open(victim).convert("RGB"))
    print(f"victim compressed to {len(compressed)} bytes "
          f"(budget {mock_pki.PHOTO_BUDGET_BYTES})")

    cases = (
        ("compressed victim vs full victim  ", victim.read_bytes(), True),
        ("compressed victim vs full attacker", attacker.read_bytes(), False),
    )

    failures = 0
    for label, other, should_match in cases:
        result = face_match.compare_faces(compressed, other)
        if not result.compared:
            print(f"{label} -> NOT COMPARED  reasons={result.reasons}")
            failures += 1
            continue

        ok = result.is_match is should_match
        failures += 0 if ok else 1
        print(f"{label} -> match={result.is_match} "
              f"distance={result.distance} threshold={result.threshold} "
              f"{'OK' if ok else 'UNEXPECTED'}")

    if failures:
        print(f"\n{failures} case(s) did not behave as required. "
              "The replay catch is NOT demonstrable as configured.")
        return 1

    print("\nFace comparison survives the QR photo budget. "
          "The replay catch can be demonstrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
