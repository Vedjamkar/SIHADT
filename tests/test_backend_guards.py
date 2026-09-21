"""Regression tests for API admission and identity-binding safety boundaries."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Importing main constructs its audit store. Keep test imports away from the
# developer's real audit database without inspecting or mutating that file.
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_TEST_DB.close()
os.unlink(_TEST_DB.name)
os.environ["AUDIT_DB_PATH"] = _TEST_DB.name

import face_match  # noqa: E402
import main  # noqa: E402
from verdict import Binding, assess  # noqa: E402


def _image_bytes(fmt: str = "PNG", size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, fmt)
    return buffer.getvalue()


class _Upload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.requested: int | None = None

    async def read(self, size: int = -1) -> bytes:
        self.requested = size
        return self.payload if size < 0 else self.payload[:size]


class TestIdentityBinding(unittest.TestCase):
    def test_successful_face_match_without_liveness_is_not_bound(self):
        result = assess(
            [], face_matched=True, liveness_passed=None, identity_attempted=True
        )
        self.assertEqual(result.identity_binding, Binding.CHECK_FAILED)

    def test_bound_requires_both_checks_to_pass(self):
        result = assess(
            [], face_matched=True, liveness_passed=True, identity_attempted=True
        )
        self.assertEqual(result.identity_binding, Binding.BOUND)

    def test_attempted_face_check_without_a_result_is_a_failure_state(self):
        result = assess(
            [], face_matched=None, liveness_passed=True, identity_attempted=True
        )
        self.assertEqual(result.identity_binding, Binding.CHECK_FAILED)

    def test_document_only_assessment_stays_not_attempted(self):
        self.assertEqual(assess([]).identity_binding, Binding.NOT_ATTEMPTED)


class TestLivenessTransitions(unittest.TestCase):
    def test_blink_requires_open_closed_open_order(self):
        self.assertTrue(face_match._blink_detected([0.25, 0.10, 0.24]))
        self.assertFalse(face_match._blink_detected([0.10, 0.25, 0.24]))
        self.assertFalse(face_match._blink_detected([0.25, 0.24, 0.23]))

    def test_unknown_challenge_is_rejected(self):
        result = face_match.check_liveness([b"x", b"y", b"z"], "wave")
        self.assertFalse(result.checked)
        self.assertIsNone(result.passed)
        self.assertEqual(result.reasons, ["LIVENESS_CHALLENGE_INVALID"])


class TestOCRRouting(unittest.TestCase):
    def test_pan_preprocessing_only_runs_in_pan_mode(self):
        fake_tesseract = SimpleNamespace(image_to_string=lambda *args, **kwargs: "")
        for pan_mode, expected_calls in ((False, 0), (True, 1)):
            with self.subTest(pan_mode=pan_mode):
                with (
                    patch.dict(sys.modules, {"pytesseract": fake_tesseract}),
                    patch.object(
                        main.ocr, "_pan_preprocessed_images", return_value=[]
                    ) as preprocess,
                ):
                    main.ocr.extract_text(_image_bytes(), pan_mode=pan_mode)
                self.assertEqual(preprocess.call_count, expected_calls)

    def test_passport_preprocessing_only_runs_in_passport_mode(self):
        fake_tesseract = SimpleNamespace(image_to_string=lambda *args, **kwargs: "")
        for passport_mode, expected_calls in ((False, 0), (True, 1)):
            with self.subTest(passport_mode=passport_mode):
                with (
                    patch.dict(sys.modules, {"pytesseract": fake_tesseract}),
                    patch.object(
                        main.ocr, "_passport_preprocessed_images", return_value=[]
                    ) as preprocess,
                ):
                    main.ocr.extract_text(
                        _image_bytes(), passport_mode=passport_mode
                    )
                self.assertEqual(preprocess.call_count, expected_calls)


class TestUploadAdmission(unittest.IsolatedAsyncioTestCase):
    async def test_upload_read_is_bounded(self):
        configured = replace(main.settings, max_upload_bytes=4)
        upload = _Upload(b"12345")
        with patch.object(main, "settings", configured):
            with self.assertRaises(HTTPException) as caught:
                await main.read_upload(upload)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(upload.requested, 5)

    async def test_frame_count_is_rejected_before_any_file_is_read(self):
        uploads = [_Upload(_image_bytes()) for _ in range(31)]
        configured = replace(main.settings, max_face_frames=30)
        with patch.object(main, "settings", configured):
            with self.assertRaises(HTTPException) as caught:
                await main.read_live_frames(uploads)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertTrue(all(upload.requested is None for upload in uploads))

    async def test_too_few_frames_are_rejected_before_any_file_is_read(self):
        uploads = [_Upload(_image_bytes()) for _ in range(2)]
        with self.assertRaises(HTTPException) as caught:
            await main.read_live_frames(uploads)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertTrue(all(upload.requested is None for upload in uploads))

    def test_corrupt_image_is_a_client_error(self):
        with self.assertRaises(HTTPException) as caught:
            main.validate_image_upload(b"this is not an image")
        self.assertEqual(caught.exception.status_code, 400)

    def test_pixel_limit_is_enforced_before_pipeline_work(self):
        configured = replace(main.settings, max_image_pixels=3)
        with patch.object(main, "settings", configured):
            with self.assertRaises(HTTPException) as caught:
                main.validate_image_upload(_image_bytes(size=(2, 2)))
        self.assertEqual(caught.exception.status_code, 413)

    def test_valid_image_is_accepted_even_with_wrong_pdf_content_type(self):
        payload = _image_bytes()
        self.assertEqual(
            main.rasterise_if_pdf(payload, content_type="application/pdf"), payload
        )

    def test_corrupt_pdf_is_a_client_error(self):
        with self.assertRaises(HTTPException) as caught:
            main.rasterise_if_pdf(b"%PDF-1.7\nnot really a pdf")
        self.assertEqual(caught.exception.status_code, 400)

    def test_valid_single_page_pdf_is_rasterised_to_an_accepted_image(self):
        import pymupdf

        pdf = pymupdf.open()
        pdf.new_page(width=32, height=32)
        payload = pdf.tobytes()
        pdf.close()
        raster = main.rasterise_if_pdf(payload)
        self.assertEqual(main.validate_image_upload(raster), raster)


class TestConsentAdmission(unittest.TestCase):
    def test_missing_consent_subject_is_rejected(self):
        configured = replace(
            main.settings,
            require_consent_subject=True,
            consent_subjects=frozenset({"alice"}),
        )
        with patch.object(main, "settings", configured):
            with self.assertRaises(HTTPException) as caught:
                main.consent_gate(None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_unlisted_consent_subject_is_rejected(self):
        configured = replace(
            main.settings,
            require_consent_subject=True,
            consent_subjects=frozenset({"alice"}),
        )
        with patch.object(main, "settings", configured):
            with self.assertRaises(HTTPException) as caught:
                main.consent_gate("bob")
        self.assertEqual(caught.exception.status_code, 403)

    def test_listed_consent_subject_is_normalised(self):
        configured = replace(
            main.settings,
            require_consent_subject=True,
            consent_subjects=frozenset({"alice"}),
        )
        with patch.object(main, "settings", configured):
            self.assertEqual(main.consent_gate(" Alice "), "alice")


def tearDownModule() -> None:
    try:
        os.unlink(_TEST_DB.name)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
