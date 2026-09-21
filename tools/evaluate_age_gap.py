"""Evaluate the production face matcher on identity pairs with age gaps.

This script evaluates and optionally calibrates the decision threshold. It does
not train ArcFace, RetinaFace, or any age-progression model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REQUIRED_FIELDS = {
    "image_id",
    "subject_id",
    "image_path",
    "capture_age_years",
    "split",
    "source",
    "rights_basis",
    "synthetic",
    "sha256",
}
VALID_SPLITS = {"development", "test"}


@dataclass(frozen=True)
class Sample:
    image_id: str
    subject_id: str
    image_path: Path
    capture_age_years: float
    split: str
    source: str
    rights_basis: str
    synthetic: bool
    sha256: str


@dataclass(frozen=True)
class Pair:
    left: Sample
    right: Sample
    same_person: bool

    @property
    def age_gap_years(self) -> float:
        return abs(self.left.capture_age_years - self.right.capture_age_years)


@dataclass(frozen=True)
class PairResult:
    split: str
    pair_type: str
    left_image_id: str
    right_image_id: str
    age_gap_years: float
    compared: bool
    distance: float | None
    production_match: bool | None
    reasons: str


def parse_bool(value: str, *, field: str, row_number: int) -> bool:
    normalised = value.strip().lower()
    if normalised in {"true", "1", "yes"}:
        return True
    if normalised in {"false", "0", "no"}:
        return False
    raise ValueError(f"row {row_number}: {field} must be true or false")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path, *, verify_hashes: bool = True) -> list[Sample]:
    path = path.resolve()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"manifest missing columns: {', '.join(sorted(missing))}")

        samples: list[Sample] = []
        image_ids: set[str] = set()
        subject_splits: dict[str, str] = {}
        for row_number, row in enumerate(reader, start=2):
            image_id = row["image_id"].strip()
            subject_id = row["subject_id"].strip()
            split = row["split"].strip().lower()
            if not image_id or not subject_id:
                raise ValueError(
                    f"row {row_number}: image_id and subject_id are required"
                )
            if image_id in image_ids:
                raise ValueError(f"row {row_number}: duplicate image_id {image_id!r}")
            if split not in VALID_SPLITS:
                raise ValueError(
                    f"row {row_number}: split must be development or test, got {split!r}"
                )
            previous_split = subject_splits.setdefault(subject_id, split)
            if previous_split != split:
                raise ValueError(
                    f"row {row_number}: subject {subject_id!r} appears in both splits; "
                    "split by person to prevent identity leakage"
                )

            try:
                age = float(row["capture_age_years"])
            except ValueError as exc:
                raise ValueError(
                    f"row {row_number}: invalid capture_age_years"
                ) from exc
            if not 0 <= age <= 120:
                raise ValueError(f"row {row_number}: capture_age_years must be 0..120")
            source = row["source"].strip()
            rights_basis = row["rights_basis"].strip()
            if not source or not rights_basis:
                raise ValueError(
                    f"row {row_number}: source and rights_basis are required for provenance"
                )

            image_path = (path.parent / row["image_path"]).resolve()
            if not image_path.is_file():
                raise ValueError(f"row {row_number}: image not found: {image_path}")
            expected_hash = row["sha256"].strip().lower()
            if len(expected_hash) != 64 or any(
                c not in "0123456789abcdef" for c in expected_hash
            ):
                raise ValueError(
                    f"row {row_number}: sha256 must contain 64 hex characters"
                )
            if verify_hashes and _sha256(image_path) != expected_hash:
                raise ValueError(f"row {row_number}: sha256 mismatch for {image_path}")

            image_ids.add(image_id)
            samples.append(
                Sample(
                    image_id=image_id,
                    subject_id=subject_id,
                    image_path=image_path,
                    capture_age_years=age,
                    split=split,
                    source=source,
                    rights_basis=rights_basis,
                    synthetic=parse_bool(
                        row["synthetic"], field="synthetic", row_number=row_number
                    ),
                    sha256=expected_hash,
                )
            )
    if not samples:
        raise ValueError("manifest has no records")
    return samples


def _reservoir(items: Iterable[Pair], limit: int, rng: random.Random) -> list[Pair]:
    selected: list[Pair] = []
    for seen, item in enumerate(items, start=1):
        if len(selected) < limit:
            selected.append(item)
            continue
        replacement = rng.randrange(seen)
        if replacement < limit:
            selected[replacement] = item
    return selected


def make_pairs(
    samples: list[Sample],
    split: str,
    *,
    max_pairs_per_class: int = 500,
    seed: int = 26188,
) -> list[Pair]:
    split_samples = sorted(
        (sample for sample in samples if sample.split == split),
        key=lambda item: item.image_id,
    )
    if not split_samples:
        return []
    rng = random.Random(f"{seed}:{split}")
    all_pairs = (
        Pair(left, right, left.subject_id == right.subject_id)
        for left, right in combinations(split_samples, 2)
    )
    genuine = _reservoir(
        (pair for pair in all_pairs if pair.same_person), max_pairs_per_class, rng
    )

    # Recreate the iterator because combinations are consumed above.
    all_pairs = (
        Pair(left, right, False)
        for left, right in combinations(split_samples, 2)
        if left.subject_id != right.subject_id
    )
    impostor_limit = min(max_pairs_per_class, len(genuine))
    impostor = _reservoir(all_pairs, impostor_limit, rng) if impostor_limit else []
    return sorted(
        genuine + impostor,
        key=lambda pair: (
            not pair.same_person,
            pair.left.image_id,
            pair.right.image_id,
        ),
    )


def metrics(results: list[PairResult], threshold: float) -> dict[str, float | int]:
    usable = [
        result for result in results if result.compared and result.distance is not None
    ]
    tp = sum(
        result.pair_type == "genuine" and result.distance <= threshold
        for result in usable
    )
    fn = sum(
        result.pair_type == "genuine" and result.distance > threshold
        for result in usable
    )
    fp = sum(
        result.pair_type == "impostor" and result.distance <= threshold
        for result in usable
    )
    tn = sum(
        result.pair_type == "impostor" and result.distance > threshold
        for result in usable
    )
    genuine_total = tp + fn
    impostor_total = fp + tn
    return {
        "threshold": round(threshold, 6),
        "pairs_requested": len(results),
        "pairs_compared": len(usable),
        "completion_rate": round(len(usable) / len(results), 6) if results else 0.0,
        "true_accepts": tp,
        "false_rejects": fn,
        "false_accepts": fp,
        "true_rejects": tn,
        "false_reject_rate": round(fn / genuine_total, 6) if genuine_total else 0.0,
        "false_accept_rate": round(fp / impostor_total, 6) if impostor_total else 0.0,
    }


def calibrate_threshold(results: list[PairResult]) -> float | None:
    usable = [
        result for result in results if result.compared and result.distance is not None
    ]
    if not any(result.pair_type == "genuine" for result in usable):
        return None
    if not any(result.pair_type == "impostor" for result in usable):
        return None
    distances = sorted({float(result.distance) for result in usable})
    candidates = [0.0, *distances, 1.0]

    def objective(threshold: float) -> tuple[float, float, float]:
        report = metrics(usable, threshold)
        far = float(report["false_accept_rate"])
        frr = float(report["false_reject_rate"])
        return ((far + frr) / 2.0, far, threshold)

    return min(candidates, key=objective)


def age_bucket(age_gap: float) -> str:
    if age_gap <= 5:
        return "0-5"
    if age_gap <= 10:
        return "6-10"
    if age_gap <= 20:
        return "11-20"
    return "21+"


def evaluate_pairs(pairs: list[Pair]) -> list[PairResult]:
    import face_match

    results: list[PairResult] = []
    for index, pair in enumerate(pairs, start=1):
        print(
            f"[{index}/{len(pairs)}] {pair.left.image_id} vs {pair.right.image_id} "
            f"({'same' if pair.same_person else 'different'}, {pair.age_gap_years:g}y gap)",
            flush=True,
        )
        verdict = face_match.compare_faces(
            pair.left.image_path.read_bytes(), pair.right.image_path.read_bytes()
        )
        results.append(
            PairResult(
                split=pair.left.split,
                pair_type="genuine" if pair.same_person else "impostor",
                left_image_id=pair.left.image_id,
                right_image_id=pair.right.image_id,
                age_gap_years=round(pair.age_gap_years, 3),
                compared=verdict.compared,
                distance=verdict.distance,
                production_match=verdict.is_match,
                reasons="|".join(verdict.reasons),
            )
        )
    return results


def _model_provenance(production_threshold: float) -> dict[str, object]:
    import deepface
    import mediapipe

    weights_root = Path.home() / ".deepface" / "weights"
    files: dict[str, dict[str, object]] = {}
    for name in ("arcface_weights.h5", "retinaface.h5"):
        path = weights_root / name
        files[name] = {
            "present": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": _sha256(path) if path.is_file() else None,
        }
    return {
        "deepface_version": getattr(deepface, "__version__", "unknown"),
        "mediapipe_version": getattr(mediapipe, "__version__", "unknown"),
        "recognition_model": "ArcFace",
        "detector": "retinaface",
        "distance_metric": "cosine",
        "production_threshold": production_threshold,
        "weights": files,
    }


def write_outputs(
    output_dir: Path, results: list[PairResult], report: dict[str, object]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "pair_results.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fieldnames = (
            list(asdict(results[0]).keys())
            if results
            else [
                "split",
                "pair_type",
                "left_image_id",
                "right_image_id",
                "age_gap_years",
                "compared",
                "distance",
                "production_match",
                "reasons",
            ]
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--output", type=Path, default=REPO_ROOT / "reports" / "age_gap"
    )
    parser.add_argument(
        "--run", action="store_true", help="Run heavy DeepFace comparisons"
    )
    parser.add_argument("--skip-hash-check", action="store_true")
    parser.add_argument("--max-pairs-per-class", type=int, default=500)
    parser.add_argument("--seed", type=int, default=26188)
    args = parser.parse_args()
    if args.max_pairs_per_class < 1:
        parser.error("--max-pairs-per-class must be at least 1")

    samples = load_manifest(args.manifest, verify_hashes=not args.skip_hash_check)
    pairs = {
        split: make_pairs(
            samples,
            split,
            max_pairs_per_class=args.max_pairs_per_class,
            seed=args.seed,
        )
        for split in sorted(VALID_SPLITS)
    }
    inventory = {
        split: {
            "subjects": len(
                {sample.subject_id for sample in samples if sample.split == split}
            ),
            "images": sum(sample.split == split for sample in samples),
            "genuine_pairs": sum(pair.same_person for pair in pairs[split]),
            "impostor_pairs": sum(not pair.same_person for pair in pairs[split]),
        }
        for split in sorted(VALID_SPLITS)
    }
    print(json.dumps({"validated": True, "inventory": inventory}, indent=2))
    invalid_splits = [
        split
        for split, counts in inventory.items()
        if counts["subjects"] < 2
        or counts["genuine_pairs"] < 1
        or counts["impostor_pairs"] < 1
    ]
    if invalid_splits:
        raise ValueError(
            "each split needs at least two subjects and at least one genuine and "
            f"impostor pair; incomplete: {', '.join(invalid_splits)}"
        )
    if not args.run:
        print("Validation only. Add --run to execute the production face matcher.")
        return 0

    all_results: list[PairResult] = []
    for split in ("development", "test"):
        all_results.extend(evaluate_pairs(pairs[split]))
    import face_match

    production_threshold = float(face_match.MATCH_THRESHOLD)
    development = [result for result in all_results if result.split == "development"]
    test = [result for result in all_results if result.split == "test"]
    calibrated = calibrate_threshold(development)
    report: dict[str, object] = {
        "claim": "Evaluation of pretrained models; no model training was performed.",
        "inventory": inventory,
        "model_provenance": _model_provenance(production_threshold),
        "production_threshold": {
            "development": metrics(development, production_threshold),
            "test": metrics(test, production_threshold),
        },
        "calibrated_threshold": calibrated,
        "calibrated_test": metrics(test, calibrated)
        if calibrated is not None
        else None,
        "genuine_test_by_age_gap": {
            bucket: metrics(
                [
                    result
                    for result in test
                    if result.pair_type == "genuine"
                    and age_bucket(result.age_gap_years) == bucket
                ],
                production_threshold,
            )
            for bucket in ("0-5", "6-10", "11-20", "21+")
        },
    }
    write_outputs(args.output.resolve(), all_results, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"wrote results to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
