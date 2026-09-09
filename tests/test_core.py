"""
Core behaviour tests.

An earlier README told the team to run `python tests/test_core.py` before demo
day. That file had never existed. This is it.

Everything here was verified by hand on 2026-09-08 while fixing the QR-replay
hole; writing it down as tests is what stops a later change quietly undoing
any of it. Deliberately stdlib-only unittest, so it runs with no extra
dependency and no pytest:

    ./.venv/Scripts/python.exe -m unittest discover -s tests -v

Face matching is NOT covered here. It needs ~260 MB of model weights and
takes minutes on a cold cache, which would make this suite something nobody
runs. Use `tools/check_face_pipeline.py` for that, separately and
deliberately.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import ela  # noqa: E402
import marksheet  # noqa: E402
import verhoeff  # noqa: E402
from verdict import Verdict, assess  # noqa: E402


class TestVerhoeff(unittest.TestCase):
    """The checksum is pure arithmetic, so it is the one thing testable exactly."""

    VALID = "234567890124"

    def test_valid_number_passes(self):
        ok, _ = verhoeff.validate_aadhaar_number(self.VALID)
        self.assertTrue(ok)

    def test_single_digit_change_fails(self):
        # Verhoeff's defining property: it catches every single-digit error.
        for position in range(len(self.VALID)):
            for replacement in "0123456789":
                if replacement == self.VALID[position]:
                    continue
                mutated = (
                    self.VALID[:position] + replacement + self.VALID[position + 1:]
                )
                ok, _ = verhoeff.validate_aadhaar_number(mutated)
                self.assertFalse(
                    ok, f"{mutated} differs from {self.VALID} at {position} but passed"
                )

    def test_adjacent_transposition_fails(self):
        # Its other defining property. Only meaningful where the digits differ.
        for position in range(len(self.VALID) - 1):
            a, b = self.VALID[position], self.VALID[position + 1]
            if a == b:
                continue
            swapped = (
                self.VALID[:position] + b + a + self.VALID[position + 2:]
            )
            ok, _ = verhoeff.validate_aadhaar_number(swapped)
            self.assertFalse(ok, f"transposition at {position} passed: {swapped}")


class TestVerdictLadder(unittest.TestCase):
    """
    The verdict engine is where an honest system and a dangerous one diverge,
    so each rung is pinned individually.
    """

    def test_valid_signature_is_genuine(self):
        self.assertEqual(
            assess(["QR_SIGNATURE_VALID"]).verdict, Verdict.GENUINE_SIGNED
        )

    def test_broken_signature_is_forged(self):
        self.assertEqual(
            assess(["QR_SIGNATURE_INVALID"]).verdict, Verdict.FORGED_SIGNATURE
        )

    def test_transplanted_qr_outranks_a_valid_signature(self):
        # The replay attack. The signature is genuine and must NOT win here.
        for evidence in (
            "QR_PHOTO_MISMATCH_PRINTED",
            "OCR_QR_NUMBER_MISMATCH",
            "OCR_QR_NAME_MISMATCH",
        ):
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    assess(["QR_SIGNATURE_VALID", evidence]).verdict,
                    Verdict.SIGNED_BUT_ALTERED,
                )

    def test_signature_does_not_mask_structural_failure(self):
        # The original elif-chain bug: a valid signature suppressed a failed
        # checksum on the printed side, which is the fingerprint of a
        # transplanted QR.
        self.assertEqual(
            assess(["QR_SIGNATURE_VALID", "AADHAAR_VERHOEFF_FAILED"]).verdict,
            Verdict.STRUCTURALLY_INVALID,
        )

    def test_single_heuristic_flag_cannot_move_the_verdict(self):
        # "Never the sole cause of a flag" — enforced, not merely documented.
        result = assess(["ELA_LOCALISED_ANOMALY"])
        self.assertEqual(result.verdict, Verdict.UNVERIFIABLE)
        self.assertIn(
            "ELA_LOCALISED_ANOMALY", [item["code"] for item in result.advisory]
        )

    def test_two_heuristic_flags_ask_for_a_human(self):
        self.assertEqual(
            assess([
                "ELA_LOCALISED_ANOMALY",
                "BASELINE_IRREGULARITY_ADVISORY",
            ]).verdict,
            Verdict.NEEDS_REVIEW,
        )

    def test_nothing_known_is_unverifiable_not_a_pass(self):
        self.assertEqual(assess([]).verdict, Verdict.UNVERIFIABLE)

    def test_no_verdict_is_the_word_verified(self):
        for verdict in Verdict:
            self.assertNotIn("VERIFIED", verdict.value.upper().replace("UNVERIFIABLE", ""))


class TestMarksheetArithmetic(unittest.TestCase):
    """The deterministic marksheet check — the 'catch a fake live' moment."""

    SUBJECTS = ["ENGLISH", "MATHEMATICS", "SCIENCE", "SOCIAL SCIENCE", "INFORMATION TECH"]
    GENUINE = (
        "184 ENGLISH LNG & LIT. 079 020 099\n"
        "041 MATHEMATICS 075 019 094\n"
        "086 SCIENCE 070 018 088\n"
        "087 SOCIAL SCIENCE 072 019 091\n"
        "402 INFORMATION TECH. 068 017 085\n"
        "Total 457\n"
        "Percentage 91.4\n"
    )

    def test_consistent_totals_are_reported_consistent(self):
        result = marksheet.analyse(self.GENUINE, None, self.SUBJECTS)
        self.assertEqual(result.computed_total, 457)
        self.assertEqual(result.printed_total, 457)
        self.assertIn(marksheet.TOTAL_CONSISTENT, result.reasons)
        self.assertNotIn(marksheet.TOTAL_MISMATCH, result.reasons)

    def test_inflated_total_is_caught(self):
        forged = self.GENUINE.replace("Total 457", "Total 487")
        result = marksheet.analyse(forged, None, self.SUBJECTS)
        self.assertIn(marksheet.TOTAL_MISMATCH, result.reasons)
        self.assertEqual(
            assess(result.reasons).verdict, Verdict.STRUCTURALLY_INVALID
        )

    def test_genuine_marksheet_reaches_only_unverifiable(self):
        # Not a bug. A marksheet carries no cryptographic anchor, so "no
        # forgery detected" is the honest ceiling and must never read as a pass.
        result = marksheet.analyse(self.GENUINE, None, self.SUBJECTS)
        self.assertEqual(assess(result.reasons).verdict, Verdict.UNVERIFIABLE)

    def test_missing_total_is_not_a_mismatch(self):
        # A missing figure must not manufacture an accusation.
        without = "\n".join(
            line for line in self.GENUINE.splitlines()
            if "Total" not in line and "Percentage" not in line
        )
        result = marksheet.analyse(without, None, self.SUBJECTS)
        self.assertIsNone(result.printed_total)
        self.assertNotIn(marksheet.TOTAL_MISMATCH, result.reasons)


class TestCertificatePinning(unittest.TestCase):
    """
    Without pinning, the trust decision is "whatever file sits at this path".
    Anyone who can drop a self-signed certificate into certs/ can then have
    their own forgeries verify as genuine — the signature check still passes,
    just against the attacker's key.
    """

    CERT = ROOT / "certs" / "mock_uidai.cer"

    def setUp(self):
        if not self.CERT.exists():
            self.skipTest(
                "no mock certificate; run: python tools/mock_pki.py init"
            )
        import aadhaar_qr

        self.aadhaar_qr = aadhaar_qr
        self.fingerprint = aadhaar_qr.certificate_fingerprint(str(self.CERT))

    def test_fingerprint_is_stable_sha256_hex(self):
        self.assertIsNotNone(self.fingerprint)
        self.assertEqual(len(self.fingerprint), 64)
        self.assertEqual(
            self.fingerprint,
            self.aadhaar_qr.certificate_fingerprint(str(self.CERT)),
        )

    def test_correct_fingerprint_loads(self):
        self.assertIsNotNone(
            self.aadhaar_qr.load_uidai_public_key(str(self.CERT), self.fingerprint)
        )

    def test_fingerprint_comparison_is_case_insensitive(self):
        self.assertIsNotNone(
            self.aadhaar_qr.load_uidai_public_key(
                str(self.CERT), self.fingerprint.upper()
            )
        )

    def test_wrong_fingerprint_refuses_to_load(self):
        # The security property. Refusing degrades to UNVERIFIABLE; loading
        # anyway would degrade to confidently wrong.
        self.assertIsNone(
            self.aadhaar_qr.load_uidai_public_key(str(self.CERT), "de:adbeef".replace(":", "") * 8)
        )

    def test_a_rogue_certificate_is_rejected_when_pinned(self):
        # The actual attack: a different, validly-formed certificate dropped in
        # place of the real one. It loads fine unpinned, and must not when the
        # expected fingerprint is set.
        import datetime
        import tempfile

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rogue")])
        now = datetime.datetime.now(datetime.timezone.utc)
        rogue = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256())
        )

        with tempfile.TemporaryDirectory() as workspace:
            path = str(Path(workspace) / "rogue.cer")
            with open(path, "wb") as handle:
                handle.write(rogue.public_bytes(serialization.Encoding.PEM))

            # Unpinned, it is accepted — this is the vulnerability.
            self.assertIsNotNone(self.aadhaar_qr.load_uidai_public_key(path))
            # Pinned to the real certificate, it is refused.
            self.assertIsNone(
                self.aadhaar_qr.load_uidai_public_key(path, self.fingerprint)
            )


class TestPassportMRZ(unittest.TestCase):
    """
    Checked against the specimen MRZ printed in the ICAO 9303 standard itself.

    Using the published vector matters: checksum code that is only tested
    against data it generated will agree with itself while being wrong.
    """

    # ICAO 9303 Part 3, the worked example.
    SPECIMEN = (
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
    )

    def setUp(self):
        import passport

        self.passport = passport

    def test_specimen_parses_and_every_check_digit_validates(self):
        result = self.passport.parse(self.SPECIMEN)
        self.assertTrue(result.found)
        self.assertEqual(result.surname, "ERIKSSON")
        self.assertEqual(result.given_names, "ANNA MARIA")
        self.assertEqual(result.issuing_state, "UTO")
        for name, ok in result.checks.items():
            with self.subTest(check=name):
                self.assertTrue(ok, f"{name} failed on the ICAO specimen")
        self.assertIn("MRZ_CHECKSUMS_OK", result.reasons)

    def test_altering_the_date_of_birth_breaks_its_check_and_the_composite(self):
        # The composite runs over the DOB field including its check digit, so
        # a single altered digit must fail twice. That double failure is what
        # makes this hard to forge casually.
        altered = self.SPECIMEN.replace("7408122F", "7408123F")
        result = self.passport.parse(altered)
        self.assertFalse(result.checks["date_of_birth"])
        self.assertFalse(result.checks["composite"])
        self.assertIn("MRZ_CHECK_DIGIT_FAILED", result.reasons)

    def test_altering_the_passport_number_is_caught(self):
        altered = self.SPECIMEN.replace("L898902C3", "L898902C4")
        result = self.passport.parse(altered)
        self.assertFalse(result.checks["passport_number"])

    def test_a_failed_check_digit_is_structural_not_heuristic(self):
        # Deterministic arithmetic, so it decides a verdict — unlike the
        # forensic signals, which are advisory by design.
        self.assertEqual(
            assess(["MRZ_CHECK_DIGIT_FAILED"]).verdict, Verdict.STRUCTURALLY_INVALID
        )

    def test_a_clean_passport_still_only_reaches_unverifiable(self):
        # Check digits are public arithmetic; a forger recomputes them. The
        # real anchor is the eMRTD chip, unreachable from a photograph.
        self.assertEqual(
            assess(["MRZ_CHECKSUMS_OK"]).verdict, Verdict.UNVERIFIABLE
        )

    def test_expiry_alone_is_not_treated_as_forgery(self):
        self.assertEqual(
            assess(["MRZ_CHECKSUMS_OK", "MRZ_DOCUMENT_EXPIRED"]).verdict,
            Verdict.UNVERIFIABLE,
        )

    def test_missing_mrz_is_reported_as_missing_not_invalid(self):
        # A passport photographed without its MRZ in frame is a capture
        # problem, not a forgery, and must never be reported as one.
        result = self.passport.parse("REPUBLIC OF SOMEWHERE\nPASSPORT\n")
        self.assertFalse(result.found)
        self.assertIn("MRZ_NOT_FOUND", result.reasons)
        self.assertEqual(assess(result.reasons).verdict, Verdict.UNVERIFIABLE)

    def test_mrz_fields_are_redacted_for_display(self):
        result = self.passport.parse(self.SPECIMEN)
        shown = result.redacted()
        self.assertEqual(shown["surname"], "E" + "*" * 7)
        self.assertNotIn("ERIKSSON", str(shown))


class TestForensics(unittest.TestCase):
    """
    The property that matters most here is the absence of false accusations.

    The first version of the screen-replay detector flagged every genuine card
    front, because a document is full of legitimate periodic structure — text
    baselines, ruled lines, the QR itself. Excluding the spectrum's axes fixed
    it. These tests exist so that fix cannot silently regress.
    """

    SPECIMENS = sorted((ROOT / "demo_data").glob("*.png"))

    def setUp(self):
        if not self.SPECIMENS:
            self.skipTest("no specimens; run: python tools/mock_pki.py card")
        import forensics

        self.forensics = forensics

    @staticmethod
    def _simulate_screen_photo(path, period=3.4, strength=0.16, angle_deg=12):
        """
        A genuine image plus an off-axis sinusoidal grid.

        This is the beat pattern a camera picks up when photographing an LCD.
        Angled deliberately, so it does not land on the spectrum axes where
        the detector (correctly) ignores things.
        """
        import io

        import numpy as np
        from PIL import Image

        array = np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0
        height, width = array.shape
        yy, xx = np.mgrid[0:height, 0:width]
        angle = np.deg2rad(angle_deg)
        grid = np.sin(2 * np.pi * (xx * np.cos(angle) + yy * np.sin(angle)) / period)
        buffer = io.BytesIO()
        Image.fromarray((np.clip(array + strength * grid, 0, 1) * 255).astype("uint8")).save(
            buffer, "PNG"
        )
        return buffer.getvalue()

    def test_no_genuine_specimen_is_called_a_screen_photo(self):
        # The regression guard. Every one of these is a real document image.
        for path in self.SPECIMENS:
            with self.subTest(specimen=path.name):
                result = self.forensics.detect_screen_replay(path.read_bytes())
                self.assertFalse(
                    result.likely_screen,
                    f"{path.name} was wrongly flagged as photographed off a screen "
                    f"({result.peak_count} off-axis peaks)",
                )

    def test_a_simulated_screen_photo_is_caught(self):
        # Sensitivity is partial and that is recorded honestly: a strong moire
        # over document-like content is caught. See the module docstring.
        card = ROOT / "demo_data" / "genuine_front.png"
        if not card.exists():
            self.skipTest("genuine_front.png not generated")
        spoofed = self._simulate_screen_photo(card)
        self.assertTrue(
            self.forensics.detect_screen_replay(spoofed).likely_screen,
            "a simulated screen photograph was not detected",
        )

    def test_no_genuine_specimen_shows_copy_move_or_noise_splice(self):
        for path in self.SPECIMENS:
            with self.subTest(specimen=path.name):
                self.assertFalse(
                    self.forensics.detect_noise_inconsistency(path.read_bytes()).inconsistent
                )

    def test_every_forensic_code_is_translatable(self):
        # An emitted code with no REASON_TEXT entry reaches the UI as an
        # untranslatable string — the same defect class already fixed twice.
        from verdict import REASON_TEXT

        bundle = self.forensics.analyse_all(self.SPECIMENS[0].read_bytes())
        for code in bundle["reasons"]:
            with self.subTest(code=code):
                self.assertIn(code, REASON_TEXT)

    def test_a_single_forensic_signal_cannot_move_a_verdict(self):
        # These are heuristic by design; one alone stays advisory.
        for code in (
            "SCREEN_REPLAY_SUSPECTED",
            "NOISE_INCONSISTENT",
            "METADATA_EDITOR_PRESENT",
        ):
            with self.subTest(code=code):
                self.assertEqual(assess([code]).verdict, Verdict.UNVERIFIABLE)

    def test_cryptographic_proof_outranks_a_forensic_hunch(self):
        self.assertEqual(
            assess(["QR_SIGNATURE_VALID", "NOISE_INCONSISTENT"]).verdict,
            Verdict.GENUINE_SIGNED,
        )

    def test_copy_move_never_accuses(self):
        # It showed no separation between a planted forgery and a genuine
        # card, so it must report a measurement and never an accusation.
        # See the VALIDATION note in forensics.detect_copy_move.
        from verdict import TIER_OF_REASON

        for path in self.SPECIMENS:
            codes = self.forensics.detect_copy_move(path.read_bytes()).reasons
            for code in codes:
                self.assertNotIn("SUSPECTED", code)
        self.assertNotIn("COPY_MOVE_SUSPECTED", TIER_OF_REASON)


class TestELAThresholds(unittest.TestCase):
    """
    Guards the arithmetic relationship that was wrong for the whole project's
    life: the firing threshold sat below its own null rate, so ELA flagged
    nearly every image.
    """

    # P(x > mean + k*sigma) for a normal distribution.
    NULL_RATE_BY_SIGMA = {2.5: 0.0062, 3.0: 0.00135}

    def test_firing_threshold_sits_above_the_null_rate(self):
        null_rate = self.NULL_RATE_BY_SIGMA.get(ela.FLAG_SIGMA)
        if null_rate is None:
            self.skipTest(f"no null rate recorded for sigma {ela.FLAG_SIGMA}")
        self.assertGreater(
            ela.MIN_FLAGGED_FRACTION,
            null_rate * 5,
            "MIN_FLAGGED_FRACTION must clear the chance rate by a wide margin, "
            "or ELA fires on untouched images",
        )

    def test_non_jpeg_is_reported_inapplicable(self):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 200, 200)).save(buffer, "PNG")
        result = ela.analyse(buffer.getvalue())
        self.assertFalse(result.applicable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
