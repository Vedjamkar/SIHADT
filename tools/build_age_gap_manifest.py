"""Build a provenance-rich manifest for cross-age face verification.

Expected image layout::

    <root>/development/<subject_id>/age-18__id-photo.jpg
    <root>/development/<subject_id>/age-24__current.jpg
    <root>/test/<different_subject_id>/age-21__id-photo.jpg
    <root>/test/<different_subject_id>/age-31__current.jpg

Subjects must not appear in both splits. Images are referenced in place; this
tool does not copy biometric data or infer a person's age from their face.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".jp2"}
AGE_PATTERN = re.compile(r"(?:^|__)age-(\d+(?:\.\d+)?)(?:__|$)", re.IGNORECASE)
FIELDS = (
    "image_id",
    "subject_id",
    "image_path",
    "capture_age_years",
    "split",
    "source",
    "rights_basis",
    "synthetic",
    "sha256",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_rows(
    image_root: Path,
    manifest_path: Path,
    source: str,
    rights_basis: str,
    synthetic: bool,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for split in ("development", "test"):
        split_root = image_root / split
        if not split_root.exists():
            continue
        for path in sorted(item for item in split_root.rglob("*") if item.is_file()):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            relative_to_split = path.relative_to(split_root)
            if len(relative_to_split.parts) < 2:
                raise ValueError(
                    f"{path}: put each image inside a subject directory, "
                    f"for example {split}/P001/age-18__capture.jpg"
                )
            subject_id = relative_to_split.parts[0].strip()
            match = AGE_PATTERN.search(path.stem)
            if not match:
                raise ValueError(
                    f"{path}: filename must contain age-<years>, for example "
                    "age-18__capture.jpg"
                )
            age = float(match.group(1))
            if not 0 <= age <= 120:
                raise ValueError(f"{path}: capture age must be between 0 and 120")

            image_id = f"{split}-{subject_id}-{path.stem}"
            if image_id in seen_ids:
                raise ValueError(f"duplicate image_id generated: {image_id}")
            seen_ids.add(image_id)

            relative_to_manifest = Path(
                os.path.relpath(path.resolve(), manifest_path.parent.resolve())
            )
            rows.append(
                {
                    "image_id": image_id,
                    "subject_id": subject_id,
                    "image_path": relative_to_manifest.as_posix(),
                    "capture_age_years": f"{age:g}",
                    "split": split,
                    "source": source,
                    "rights_basis": rights_basis,
                    "synthetic": str(synthetic).lower(),
                    "sha256": _sha256(path),
                }
            )

    if not rows:
        raise ValueError(f"no supported images found under {image_root}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--source", required=True, help="Dataset or capture source name"
    )
    parser.add_argument(
        "--rights-basis",
        required=True,
        help="Consent record or dataset licence identifier; do not put personal data here",
    )
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    image_root = args.image_root.resolve()
    manifest = args.manifest.resolve()
    rows = collect_rows(
        image_root=image_root,
        manifest_path=manifest,
        source=args.source,
        rights_basis=args.rights_basis,
        synthetic=args.synthetic,
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} records to {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
