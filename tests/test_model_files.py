"""
Model files are not in git. These tests pin the behaviour that makes that
survivable: the manifest is complete, a missing file fails fast with the fix
in the message instead of triggering an in-request download, and the fetch
tool never installs a file that does not match the manifest.

No network, no TensorFlow, no mediapipe import. Stdlib plus Pillow only.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_TEST_DB.close()
os.unlink(_TEST_DB.name)
os.environ["AUDIT_DB_PATH"] = _TEST_DB.name

import face_match  # noqa: E402
import fetch_models  # noqa: E402
import main  # noqa: E402


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "JPEG")
    return buffer.getvalue()


class ManifestTests(unittest.TestCase):
    def test_every_entry_is_fully_pinned(self):
        for entry in face_match.REQUIRED_MODELS:
            with self.subTest(entry["path"]):
                self.assertTrue(entry["url"].startswith("https://"))
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(entry["size"], 0)
                self.assertFalse(Path(entry["path"]).is_absolute())

    def test_deepface_files_live_where_deepface_looks(self):
        # DeepFace and RetinaFace hard-code `$DEEPFACE_HOME/.deepface/weights`.
        deepface_paths = [e["path"] for e in face_match.REQUIRED_MODELS if e["path"].endswith(".h5")]
        self.assertTrue(deepface_paths)
        for relative in deepface_paths:
            self.assertTrue(relative.startswith(".deepface/weights/"), relative)
        self.assertEqual(os.environ.get("DEEPFACE_HOME"), str(face_match.MODELS_DIR))

    def test_landmarker_path_is_in_manifest(self):
        paths = {face_match.MODELS_DIR / e["path"] for e in face_match.REQUIRED_MODELS}
        self.assertIn(face_match.FACE_LANDMARKER_PATH, paths)


class MissingModelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.empty = Path(self._tmp.name)
        self._patch = patch.object(face_match, "MODELS_DIR", self.empty)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_missing_models_lists_everything_when_dir_is_empty(self):
        absent = face_match.missing_models()
        self.assertEqual(absent, [e["path"] for e in face_match.REQUIRED_MODELS])
        status = face_match.models_status()
        self.assertFalse(status["face_models_ready"])
        self.assertEqual(status["face_models_missing"], absent)

    def test_zero_length_file_counts_as_missing(self):
        target = self.empty / face_match.REQUIRED_MODELS[0]["path"]
        target.parent.mkdir(parents=True)
        target.touch()
        self.assertIn(face_match.REQUIRED_MODELS[0]["path"], face_match.missing_models())

    def test_compare_faces_fails_fast_without_importing_deepface(self):
        with patch.dict(sys.modules, {"deepface": None}):
            result = face_match.compare_faces(_jpeg(), _jpeg())
        self.assertFalse(result.compared)
        self.assertEqual(result.reasons, ["FACE_MATCH_ERROR"])
        self.assertEqual(result.detail["error_type"], "ModelFilesMissing")
        self.assertIn("fetch_models.py", result.detail["error"])

    def test_age_gap_is_unavailable_not_an_error(self):
        with patch.dict(sys.modules, {"deepface": None}):
            result = face_match.check_age_gap(_jpeg(), _jpeg())
        self.assertFalse(result.checked)
        self.assertEqual(result.reasons, ["AGE_ESTIMATION_UNAVAILABLE"])

    def test_liveness_reports_backend_unavailable_before_touching_mediapipe(self):
        with patch.dict(sys.modules, {"mediapipe": None}):
            result = face_match.check_liveness([_jpeg()] * 3, "blink")
        self.assertFalse(result.checked)
        self.assertEqual(result.reasons, ["LIVENESS_BACKEND_UNAVAILABLE"])
        self.assertIn("face_landmarker.task", result.detail["error"])

    def test_health_reports_model_status(self):
        payload = main.health()
        self.assertIn("face_models_ready", payload)
        self.assertFalse(payload["face_models_ready"])
        self.assertEqual(payload["face_models_dir"], str(self.empty))


class FetchToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.payload = b"not really weights"
        self.entry = {
            "path": "sub/model.bin",
            "url": "https://example.invalid/model.bin",
            "sha256": hashlib.sha256(self.payload).hexdigest(),
            "size": len(self.payload),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_verify_file_catches_size_and_hash_mismatch(self):
        good = self.dir / "good"
        good.write_bytes(self.payload)
        self.assertIsNone(fetch_models.verify_file(good, self.entry))

        wrong_size = self.dir / "short"
        wrong_size.write_bytes(self.payload[:-1])
        self.assertIn("size", fetch_models.verify_file(wrong_size, self.entry))

        wrong_hash = self.dir / "flipped"
        wrong_hash.write_bytes(b"X" + self.payload[1:])
        self.assertIn("sha256", fetch_models.verify_file(wrong_hash, self.entry))

        self.assertEqual(fetch_models.verify_file(self.dir / "nope", self.entry), "missing")

    def test_install_refuses_mismatch_and_leaves_no_partial(self):
        source = self.dir / "src"
        source.write_bytes(b"garbage")
        destination = self.dir / "dest" / "model.bin"
        with self.assertRaises(ValueError):
            fetch_models._install(source, destination, self.entry, move=False)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.dir.glob("dest/*")))

    def test_install_places_verified_file_atomically(self):
        source = self.dir / "src"
        source.write_bytes(self.payload)
        destination = self.dir / "dest" / "model.bin"
        fetch_models._install(source, destination, self.entry, move=True)
        self.assertEqual(destination.read_bytes(), self.payload)
        self.assertFalse(source.exists())
        leftovers = [p for p in destination.parent.iterdir() if p != destination]
        self.assertEqual(leftovers, [])

    def test_check_mode_reports_missing_without_network(self):
        with patch.object(fetch_models, "MODELS_DIR", self.dir), patch.object(
            face_match, "REQUIRED_MODELS", (self.entry,)
        ), patch("fetch_models.download") as download, contextlib.redirect_stdout(io.StringIO()):
            code = fetch_models.main(["--check"])
        self.assertEqual(code, 1)
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
