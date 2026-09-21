"""Fast endpoint-contract tests with heavyweight document/face work mocked."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_TEST_DB.close()
os.unlink(_TEST_DB.name)
os.environ["AUDIT_DB_PATH"] = _TEST_DB.name

import aadhaar_qr  # noqa: E402
import ela  # noqa: E402
import face_match  # noqa: E402
import main  # noqa: E402
import ocr  # noqa: E402
import passport  # noqa: E402


class TestEmbeddedPdfQR(unittest.TestCase):
    def test_original_qr_is_read_when_page_rendering_makes_it_tiny(self):
        import pymupdf
        import qrcode
        payload = '<PrintLetterBarcodeData uid="000000000000" name="SYNTHETIC TEST" />'
        image = io.BytesIO()
        qrcode.make(payload).save(image, format="PNG")
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_image(pymupdf.Rect(50, 50, 70, 70), stream=image.getvalue())
            original = pdf.tobytes()
        rendered = main.rasterise_if_pdf(original)
        result = main.verify_upload_qr(original, rendered)
        self.assertEqual(result.version, "V1")
        self.assertIsNone(result.signature_verified)

    def test_non_pdf_uses_existing_image_decoder(self):
        with patch.object(aadhaar_qr, "verify_aadhaar_image") as decoder:
            main.verify_upload_qr(b"image", b"rendered")
            decoder.assert_called_once_with(b"rendered", main.UIDAI_KEY)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    return buffer.getvalue()


class _Upload:
    content_type = "image/png"

    def __init__(self, payload: bytes):
        self.payload = payload

    async def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


EMPTY_ELA = ela.ELAResult(
    applicable=False,
    source_format="PNG",
    mean_error=0.0,
    max_error=0.0,
    flagged_blocks=[],
    flagged_fraction=0.0,
    heatmap_png_base64=None,
    reasons=[],
)


class TestDocumentEndpointContracts(unittest.IsolatedAsyncioTestCase):
    """Exercise every verdict through the real Aadhaar endpoint envelope."""

    CASES = {
        "GENUINE_SIGNED": ["QR_SIGNATURE_VALID"],
        "FORGED_SIGNATURE": ["QR_SIGNATURE_INVALID"],
        "SIGNED_BUT_ALTERED": [
            "QR_SIGNATURE_VALID",
            "QR_PHOTO_MISMATCH_PRINTED",
        ],
        "STRUCTURALLY_INVALID": ["AADHAAR_VERHOEFF_FAILED"],
        "NEEDS_REVIEW": [
            "ELA_LOCALISED_ANOMALY",
            "BASELINE_IRREGULARITY_ADVISORY",
        ],
        "UNVERIFIABLE": ["QR_NOT_FOUND"],
    }

    async def _verify(self, reasons: list[str], payload: bytes | None = None) -> dict:
        qr = aadhaar_qr.AadhaarQRResult(
            version="V2" if "QR_NOT_FOUND" not in reasons else "UNKNOWN",
            signature_verified=(
                True if "QR_SIGNATURE_VALID" in reasons
                else False if "QR_SIGNATURE_INVALID" in reasons
                else None
            ),
            fields={},
            reasons=reasons,
        )
        text = ocr.OCRResult(engine="mock", text="")
        forensic = {"reasons": []}
        with (
            patch.object(main.aadhaar_qr, "verify_aadhaar_image", return_value=qr),
            patch.object(main.ocr, "extract_text", return_value=text),
            patch.object(main.ela, "analyse", return_value=EMPTY_ELA),
            patch.object(main.forensics, "analyse_all", return_value=forensic),
            patch.object(main.forensics, "render_maps", return_value={}),
            patch.object(main.store, "record", return_value="test-record"),
        ):
            return await main.verify_aadhaar(_Upload(payload or _png()), None)

    async def test_all_six_verdicts_use_the_public_response_contract(self):
        expected_keys = {
            "record_id", "verdict", "headline", "decided_by",
            "identity_binding", "reasons", "advisory", "details", "disclaimer",
        }
        for expected, reasons in self.CASES.items():
            with self.subTest(verdict=expected):
                response = await self._verify(reasons)
                self.assertEqual(set(response), expected_keys)
                self.assertEqual(response["verdict"], expected)
                self.assertEqual(response["identity_binding"], "NOT_ATTEMPTED")
                self.assertEqual(response["record_id"], "test-record")
                self.assertEqual(response["disclaimer"], main.DISCLAIMER)
                self.assertIsInstance(response["details"], dict)

    async def test_generated_document_specimen_reaches_the_endpoint_boundary(self):
        specimen = ROOT / "demo_data" / "genuine_front.png"
        if not specimen.exists():
            self.skipTest("generated genuine_front.png specimen is absent")
        response = await self._verify(["QR_NOT_FOUND"], specimen.read_bytes())
        self.assertEqual(response["verdict"], "UNVERIFIABLE")
        self.assertEqual(response["details"]["qr_version"], "UNKNOWN")


class TestPassportEndpointContract(unittest.IsolatedAsyncioTestCase):
    SPECIMEN = (
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
    )

    async def test_passport_route_uses_targeted_ocr_and_returns_redacted_mrz(self):
        text = ocr.OCRResult(engine="mock", text=self.SPECIMEN)
        mrz = passport.parse(self.SPECIMEN)
        forensic = {"reasons": []}
        with (
            patch.object(main.ocr, "extract_text", return_value=text) as extract,
            patch.object(main.ela, "analyse", return_value=EMPTY_ELA),
            patch.object(main.forensics, "analyse_all", return_value=forensic),
            patch.object(main.forensics, "render_maps", return_value={}),
            patch.object(main.store, "record", return_value="passport-record") as record,
        ):
            response = await main.verify_passport(_Upload(_png()))

        extract.assert_called_once_with(_png(), passport_mode=True)
        self.assertEqual(response["record_id"], "passport-record")
        self.assertEqual(response["verdict"], "UNVERIFIABLE")
        self.assertTrue(response["details"]["mrz_found"])
        self.assertEqual(response["details"]["mrz"], mrz.redacted())
        self.assertNotIn("ERIKSSON", str(response))
        self.assertIsNone(response["details"]["ela"]["heatmap_png_base64"])
        self.assertEqual(record.call_args.kwargs["doc_type"], "passport")


class TestFaceEndpointContracts(unittest.IsolatedAsyncioTestCase):
    """Exercise each attempted binding state through /verify/face."""

    CASES = {
        "BOUND": (True, True),
        "NOT_BOUND": (False, True),
        "LIVENESS_FAILED": (True, False),
        "CHECK_FAILED": (True, None),
    }

    async def test_all_five_binding_states_are_representable_by_endpoints(self):
        seen = {"NOT_ATTEMPTED"}  # Every document-only endpoint returns this.
        for expected, (matched, live) in self.CASES.items():
            with self.subTest(binding=expected):
                match = face_match.FaceMatchResult(
                    compared=matched is not None,
                    distance=0.1 if matched else None,
                    similarity=0.9 if matched else None,
                    is_match=matched,
                    threshold=0.68,
                    model="mock",
                    reasons=[],
                )
                liveness = face_match.LivenessResult(
                    checked=live is not None,
                    passed=live,
                    challenge="blink" if live is not None else None,
                    reasons=[],
                )
                age_gap = face_match.AgeGapResult(
                    checked=False,
                    id_age=None,
                    selfie_age=None,
                    gap_years=None,
                    threshold_years=12,
                    reasons=["AGE_ESTIMATION_UNAVAILABLE"],
                )
                with (
                    patch.object(main, "consent_gate", return_value="synthetic"),
                    patch.object(main, "read_live_frames", new=AsyncMock(return_value=[_png()] * 3)),
                    patch.object(main.face_match, "compare_faces", return_value=match),
                    patch.object(main.face_match, "check_liveness", return_value=liveness),
                    # Unpatched, this runs the real age model. With the model
                    # files present that is TensorFlow plus ~2 minutes; the
                    # binding states under test never depend on it.
                    patch.object(main.face_match, "check_age_gap", return_value=age_gap),
                    patch.object(main.store, "record", return_value="face-record"),
                ):
                    response = await main.verify_face(
                        _Upload(_png()), [], "synthetic", "blink"
                    )
                self.assertEqual(response["identity_binding"], expected)
                self.assertEqual(response["details"]["face"]["is_match"], matched)
                self.assertEqual(response["details"]["liveness"]["passed"], live)
                self.assertNotIn("frames", response)
                self.assertNotIn("id_photo", response)
                seen.add(response["identity_binding"])

        self.assertEqual(
            seen,
            {"BOUND", "NOT_BOUND", "LIVENESS_FAILED", "CHECK_FAILED", "NOT_ATTEMPTED"},
        )


def tearDownModule() -> None:
    try:
        os.unlink(_TEST_DB.name)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
