"""
Generate forged specimens that the forensic detectors should catch.

Two jobs at once.

First, a positive control. A detector that has only ever been tested against
genuine documents is untested: it might be catching real forgeries, or it
might be incapable of firing at all, and there is no way to tell them apart
from the outside. These are deliberate forgeries with known ground truth.

Second, demo material. "It flagged nothing on six genuine cards" is a weak
thing to show. Being handed a forgery and watching it get caught is not.

Everything produced is synthetic and derived from the mock specimens, so
nothing here involves a real person's document.

Usage
-----
    ./.venv/Scripts/python.exe tools/make_forgeries.py
    ./.venv/Scripts/python.exe tools/make_forgeries.py --publish   # serve at /demo/
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import forensics  # noqa: E402

DEMO = ROOT / "demo_data"
PUBLIC = ROOT / "frontend" / "public" / "demo"


def copy_move_forgery(source: Path, dest: Path) -> None:
    """
    Paste a patch of the card over another part of it.

    The commonest crude document edit: cover an inconvenient value with a
    clean piece of the same card, so the texture and colour match perfectly
    and nothing looks wrong to the eye. What gives it away is that the patch
    is byte-for-byte a region that already exists elsewhere in the image.
    """
    image = Image.open(source).convert("RGB")
    width, height = image.size

    # Take a patch from a busy area and stamp it over a different busy area,
    # so the duplication is genuine rather than two blank regions matching.
    patch_box = (int(width * 0.14), int(height * 0.22),
                 int(width * 0.40), int(height * 0.40))
    patch = image.crop(patch_box)
    image.paste(patch, (int(width * 0.52), int(height * 0.55)))

    image.save(dest)


def screen_replay_forgery(source: Path, dest: Path,
                          period: float = 3.4, strength: float = 0.16,
                          angle_deg: float = 12.0) -> None:
    """
    Simulate photographing the document off a screen.

    A camera aimed at an LCD samples the display's pixel grid; the two grids
    beat and leave a periodic interference pattern. Modelled here as an
    off-axis sinusoid — off-axis deliberately, because a document's own
    regular structure (text baselines, rules, the QR) lives on the axes, and
    the detector ignores those precisely so it does not accuse honest
    documents.
    """
    array = np.asarray(Image.open(source).convert("RGB"), dtype=np.float32) / 255.0
    height, width = array.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    angle = np.deg2rad(angle_deg)
    grid = np.sin(2 * np.pi * (xx * np.cos(angle) + yy * np.sin(angle)) / period)
    out = np.clip(array + strength * grid[:, :, None], 0, 1)
    Image.fromarray((out * 255).astype("uint8")).save(dest)


def splice_forgery(source: Path, donor: Path, dest: Path) -> None:
    """
    Splice a region from a different image in.

    The donor is a photograph, so the pasted region carries a different
    sensor-noise signature from its surroundings — which is exactly what the
    noise-inconsistency detector looks for.
    """
    base = Image.open(source).convert("RGB")
    patch = Image.open(donor).convert("RGB")

    width, height = base.size
    box_w, box_h = int(width * 0.30), int(height * 0.34)
    patch = patch.resize((box_w, box_h), Image.LANCZOS)
    base.paste(patch, (int(width * 0.55), int(height * 0.18)))

    base.save(dest)


def report(label: str, path: Path, expect: str) -> bool:
    """Run every detector and say whether the expected one actually fired."""
    data = path.read_bytes()
    bundle = forensics.analyse_all(data)
    fired = expect in bundle["reasons"]
    mark = "caught" if fired else "MISSED"
    print(f"  {label:22} {mark:7} {bundle['reasons']}")
    return fired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true",
                        help="copy into frontend/public/demo/ so the UI can load them")
    args = parser.parse_args()

    card = DEMO / "genuine_front.png"
    donor = DEMO / "faces" / "victim.jpg"
    if not card.exists():
        print("missing demo_data/genuine_front.png — run tools/mock_pki.py card first")
        return 2

    out = DEMO / "forgeries"
    out.mkdir(parents=True, exist_ok=True)

    copy_move_forgery(card, out / "forged_copy_move.png")
    screen_replay_forgery(card, out / "forged_screen_replay.png")
    if donor.exists():
        splice_forgery(card, donor, out / "forged_splice.png")

    print("Forged specimens, and whether the detector caught them:")
    results = [
        report("copy-move", out / "forged_copy_move.png", "COPY_MOVE_SUSPECTED"),
        report("screen replay", out / "forged_screen_replay.png", "SCREEN_REPLAY_SUSPECTED"),
    ]
    if (out / "forged_splice.png").exists():
        results.append(report("splice", out / "forged_splice.png", "NOISE_INCONSISTENT"))

    print("\nControl — the genuine card must stay clean:")
    clean = forensics.analyse_all(card.read_bytes())
    accusations = [c for c in clean["reasons"]
                   if c.endswith(("_SUSPECTED", "_INCONSISTENT"))]
    print(f"  {'genuine_front':22} {'clean' if not accusations else 'FALSE POSITIVE'} "
          f"{clean['reasons']}")

    caught = sum(results)
    print(f"\ncaught {caught}/{len(results)} forgeries, "
          f"{len(accusations)} false positives on the genuine card")

    if args.publish:
        PUBLIC.mkdir(parents=True, exist_ok=True)
        for item in out.glob("*.png"):
            shutil.copy2(item, PUBLIC / item.name)
        print(f"published to {PUBLIC}")

    # A missed forgery is a finding worth reporting, not a crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
