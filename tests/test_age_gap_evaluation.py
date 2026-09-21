from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from build_age_gap_manifest import FIELDS, collect_rows
from evaluate_age_gap import (
    PairResult,
    Sample,
    age_bucket,
    calibrate_threshold,
    load_manifest,
    make_pairs,
    metrics,
)


def sample(image_id: str, subject: str, age: float, split: str) -> Sample:
    return Sample(
        image_id=image_id,
        subject_id=subject,
        image_path=Path(f"{image_id}.jpg"),
        capture_age_years=age,
        split=split,
        source="test",
        rights_basis="test-fixture",
        synthetic=True,
        sha256="0" * 64,
    )


def result(pair_type: str, distance: float) -> PairResult:
    return PairResult(
        split="test",
        pair_type=pair_type,
        left_image_id="left",
        right_image_id="right",
        age_gap_years=10,
        compared=True,
        distance=distance,
        production_match=distance <= 0.68,
        reasons="",
    )


class AgeGapEvaluationTests(unittest.TestCase):
    def test_manifest_round_trip_records_hashes_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_root = root / "images"
            for split, subject in (
                ("development", "P001"),
                ("development", "P002"),
                ("test", "P101"),
                ("test", "P102"),
            ):
                directory = image_root / split / subject
                directory.mkdir(parents=True)
                (directory / "age-20__younger.jpg").write_bytes(
                    f"{split}-{subject}-younger".encode()
                )
                (directory / "age-30__current.jpg").write_bytes(
                    f"{split}-{subject}-current".encode()
                )

            manifest = root / "metadata.csv"
            rows = collect_rows(
                image_root,
                manifest,
                source="unit-test",
                rights_basis="test-fixture",
                synthetic=True,
            )
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            samples = load_manifest(manifest)
            self.assertEqual(len(samples), 8)
            self.assertTrue(all(item.synthetic for item in samples))
            self.assertTrue(all(len(item.sha256) == 64 for item in samples))

    def test_pairs_balance_genuine_and_impostor(self) -> None:
        samples = [
            sample("a1", "A", 20, "test"),
            sample("a2", "A", 30, "test"),
            sample("b1", "B", 21, "test"),
            sample("b2", "B", 31, "test"),
        ]
        pairs = make_pairs(samples, "test", max_pairs_per_class=10)
        self.assertEqual(sum(pair.same_person for pair in pairs), 2)
        self.assertEqual(sum(not pair.same_person for pair in pairs), 2)

    def test_metrics_use_distance_in_correct_direction(self) -> None:
        report = metrics(
            [
                result("genuine", 0.2),
                result("genuine", 0.8),
                result("impostor", 0.3),
                result("impostor", 0.9),
            ],
            0.68,
        )
        self.assertEqual(report["false_reject_rate"], 0.5)
        self.assertEqual(report["false_accept_rate"], 0.5)

    def test_calibration_uses_labelled_development_distances(self) -> None:
        threshold = calibrate_threshold(
            [
                result("genuine", 0.2),
                result("genuine", 0.3),
                result("impostor", 0.7),
                result("impostor", 0.8),
            ]
        )
        self.assertIsNotNone(threshold)
        self.assertGreaterEqual(threshold, 0.3)
        self.assertLess(threshold, 0.7)

    def test_age_buckets(self) -> None:
        self.assertEqual(age_bucket(5), "0-5")
        self.assertEqual(age_bucket(10), "6-10")
        self.assertEqual(age_bucket(20), "11-20")
        self.assertEqual(age_bucket(21), "21+")


if __name__ == "__main__":
    unittest.main()
