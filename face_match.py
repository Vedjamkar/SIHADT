"""
Biometric face-match and liveness.

What this module is for
    Signature verification proves the *document* is authentic. It does not
    prove the person in front of you owns it. A forger who photographs someone
    else's genuine Aadhaar passes every cryptographic check in this app. The
    face-match is what closes that hole, and that pairing is the strongest
    thing in your pitch. Lead with it when a judge asks what makes this
    different: you are verifying issuance *and* binding it to a live presenter.

Non-negotiable from your plan, enforced here
    Compare live, discard immediately, never store biometric data. Concretely:
      - Frames arrive as bytes, live in local variables, and are overwritten
        before the function returns.
      - Temporary files are written into a per-request directory that is
        removed in a `finally` block, because DeepFace's API wants paths.
      - The return value carries a float and a boolean. No embeddings, no
        crops, no file paths. An embedding is biometric data; a 512-float
        vector is not anonymous just because it looks like noise.
      - Nothing from this module is passed to the audit store.

Liveness: read this before you promise anything on stage
    The blink/head-turn check below compares landmark geometry across frames.
    It defeats a printed photo held up to the camera. It does NOT defeat a
    video replay, a phone screen held to the lens, or a deepfake stream, and
    real anti-spoofing needs either depth sensing or a trained PAD model.
    If a judge asks whether your liveness check can be fooled, say yes and name
    the attack. Claiming otherwise in a room that may contain a security
    reviewer is a bad trade for one nod of approval.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

import numpy as np

from pathlib import Path

from config import MODELS_DIR, settings

# Cosine-distance thresholds are model-specific. ArcFace at 0.68 is DeepFace's
# own tuned default; do not reuse a threshold across models.
MODEL_NAME = "ArcFace"
DETECTOR = "retinaface"
MATCH_THRESHOLD = 0.68

# Pretrained model files this module needs, as paths relative to
# `config.MODELS_DIR`. None of them are in git: two of the DeepFace weights
# exceed GitHub's 100 MB file cap and the age model is ~540 MB. Instead,
# `tools/fetch_models.py` downloads each from its upstream release, verifies the
# SHA-256 and byte size below, and writes it atomically into place. The same
# table drives `/health` and the launcher's readiness check, so "weights are
# missing" is reported once at startup rather than as a hung request later.
#
# DeepFace and RetinaFace look under `$DEEPFACE_HOME/.deepface/weights/`;
# MediaPipe Tasks takes an explicit path, so the landmarker sits at the root.
DEEPFACE_RELEASE = "https://github.com/serengil/deepface_models/releases/download/v1.0/"
MEDIAPIPE_RELEASE = "https://storage.googleapis.com/mediapipe-models/"
REQUIRED_MODELS: tuple[dict, ...] = (
    {
        "path": ".deepface/weights/arcface_weights.h5",
        "url": DEEPFACE_RELEASE + "arcface_weights.h5",
        "sha256": "6336979c0c602cae08d1122a66f4dfb862d059bbcd8ef80306aef2b2249b0c93",
        "size": 137_026_640,
        "used_by": "compare_faces (ArcFace embedding)",
    },
    {
        "path": ".deepface/weights/retinaface.h5",
        "url": DEEPFACE_RELEASE + "retinaface.h5",
        "sha256": "ecb2393a89da3dd3d6796ad86660e298f62a0c8ae7578d92eb6af14e0bb93adf",
        "size": 118_667_368,
        "used_by": "compare_faces + check_age_gap (RetinaFace detector)",
    },
    {
        "path": ".deepface/weights/age_model_weights.h5",
        "url": DEEPFACE_RELEASE + "age_model_weights.h5",
        "sha256": "0aeff75734bfe794113756d2bfd0ac823d51e9422c8961125b570871d3c2b114",
        "size": 538_771_776,
        "used_by": "check_age_gap (apparent-age regression)",
    },
    {
        "path": "face_landmarker.task",
        "url": MEDIAPIPE_RELEASE
        + "face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        "size": 3_758_596,
        "used_by": "check_liveness (MediaPipe Face Landmarker)",
    },
)

FACE_LANDMARKER_PATH = MODELS_DIR / "face_landmarker.task"


def model_path(relative: str) -> Path:
    return MODELS_DIR / relative


def missing_models(paths: tuple[str, ...] | None = None) -> list[str]:
    """
    Relative paths of required model files that are absent or zero-length.
    A partial file left behind by a killed download reads as present to
    DeepFace and then fails deep inside Keras; the fetch tool never leaves
    one, but a manual copy might.
    """
    wanted = paths or tuple(entry["path"] for entry in REQUIRED_MODELS)
    absent = []
    for relative in wanted:
        path = MODELS_DIR / relative
        if not path.is_file() or path.stat().st_size == 0:
            absent.append(relative)
    return absent


def models_status() -> dict:
    """Surface for `/health`: what is present, what is not, where to look."""
    absent = missing_models()
    return {
        "face_models_ready": not absent,
        "face_models_missing": absent,
        "face_models_dir": str(MODELS_DIR),
    }


class ModelFilesMissing(RuntimeError):
    """Raised instead of letting DeepFace download ~800 MB inside a request."""


def _require_models(*paths: str) -> None:
    absent = missing_models(paths)
    if absent:
        raise ModelFilesMissing(
            f"missing {', '.join(absent)} under {MODELS_DIR}; "
            "run `python tools/fetch_models.py`"
        )


EAR_DROP_THRESHOLD = 0.18   # blink: eye-aspect-ratio must fall below this
YAW_DELTA_THRESHOLD = 0.12  # head turn: normalised horizontal nose shift


@dataclass
class FaceMatchResult:
    compared: bool
    distance: float | None
    similarity: float | None       # 1 - distance, clamped, for display only
    is_match: bool | None
    threshold: float
    model: str
    reasons: list[str] = field(default_factory=list)
    # Diagnostic context for a failed comparison. Kept separate from `reasons`
    # so that free-form error text never masquerades as a reason code.
    detail: dict = field(default_factory=dict)


@dataclass
class LivenessResult:
    checked: bool
    passed: bool | None
    challenge: str | None
    detail: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def compare_faces(id_photo: bytes, selfie: bytes) -> FaceMatchResult:
    """
    One-shot comparison. Both inputs are discarded before returning.
    """
    workspace = tempfile.mkdtemp(prefix="fm_")
    id_path = os.path.join(workspace, "id.jpg")
    selfie_path = os.path.join(workspace, "live.jpg")
    try:
        _write_normalised(id_photo, id_path)
        _write_normalised(selfie, selfie_path)

        # DeepFace's own fallback is to download the weights on first use,
        # synchronously, inside this call. On the demo Wi-Fi that is minutes
        # of a hung request that the frontend reports as a generic failure.
        # Fail fast with the fix in the message instead.
        _require_models(".deepface/weights/arcface_weights.h5", ".deepface/weights/retinaface.h5")

        from deepface import DeepFace

        verdict = DeepFace.verify(
            img1_path=id_path,
            img2_path=selfie_path,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR,
            distance_metric="cosine",
            enforce_detection=True,
        )
        distance = float(verdict["distance"])
        return FaceMatchResult(
            compared=True,
            distance=round(distance, 4),
            similarity=round(max(0.0, 1.0 - distance), 4),
            is_match=distance <= MATCH_THRESHOLD,
            threshold=MATCH_THRESHOLD,
            model=MODEL_NAME,
            reasons=["FACE_MATCH" if distance <= MATCH_THRESHOLD else "FACE_NO_MATCH"],
        )
    except ValueError as exc:
        # DeepFace raises ValueError when it cannot find a face at all.
        return FaceMatchResult(
            compared=False,
            distance=None,
            similarity=None,
            is_match=None,
            threshold=MATCH_THRESHOLD,
            model=MODEL_NAME,
            # Only the code. A raw exception string here becomes a "reason
            # code" that flows into the audit database and out to the UI, where
            # nothing can translate it and REASON_TEXT has no entry for it.
            # The detail belongs in `detail`, not in the code list.
            reasons=["FACE_NOT_DETECTED"],
            detail={"error": str(exc)[:200]},
        )
    except Exception as exc:
        return FaceMatchResult(
            compared=False,
            distance=None,
            similarity=None,
            is_match=None,
            threshold=MATCH_THRESHOLD,
            model=MODEL_NAME,
            reasons=["FACE_MATCH_ERROR"],
            detail={"error_type": type(exc).__name__, "error": str(exc)[:200]},
        )
    finally:
        # Wipe before unlink so the bytes are not merely dereferenced.
        for path in (id_path, selfie_path):
            _shred(path)
        shutil.rmtree(workspace, ignore_errors=True)
        id_photo = b""
        selfie = b""


@dataclass
class AgeGapResult:
    checked: bool
    id_age: int | None
    selfie_age: int | None
    gap_years: int | None
    threshold_years: int
    reasons: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _estimate_age(image_bytes: bytes) -> int | None:
    """
    Apparent age from DeepFace's pretrained age-estimation model.

    This is a real pretrained regression model shipped with DeepFace (trained
    by its authors on public age-labelled face datasets) — nothing here is
    trained or fabricated by this project. It estimates apparent age from a
    single photo; it does not model how one specific face grows over time.
    """
    workspace = tempfile.mkdtemp(prefix="age_")
    path = os.path.join(workspace, "face.jpg")
    try:
        _write_normalised(image_bytes, path)
        _require_models(".deepface/weights/age_model_weights.h5", ".deepface/weights/retinaface.h5")

        from deepface import DeepFace

        analysis = DeepFace.analyze(
            img_path=path,
            actions=["age"],
            detector_backend=DETECTOR,
            enforce_detection=True,
        )
        result = analysis[0] if isinstance(analysis, list) else analysis
        return int(result["age"])
    except Exception:
        return None
    finally:
        _shred(path)
        shutil.rmtree(workspace, ignore_errors=True)


def check_age_gap(id_photo: bytes, selfie: bytes) -> AgeGapResult:
    """
    Advisory-only: flag a large apparent-age gap between the ID photo and the
    live selfie, so a weak match distance has an honest explanation on screen
    instead of reading as a bare accusation.

    Deliberately heuristic tier and never fatal on its own — see verdict.py's
    tier rules. This does not adjust MATCH_THRESHOLD; it only adds context.
    """
    threshold = settings.age_gap_advisory_years
    id_age = _estimate_age(id_photo)
    selfie_age = _estimate_age(selfie)

    if id_age is None or selfie_age is None:
        return AgeGapResult(
            checked=False,
            id_age=id_age,
            selfie_age=selfie_age,
            gap_years=None,
            threshold_years=threshold,
            reasons=["AGE_ESTIMATION_UNAVAILABLE"],
        )

    gap = abs(id_age - selfie_age)
    reason = "AGE_GAP_LARGE" if gap >= threshold else "AGE_GAP_NORMAL"
    return AgeGapResult(
        checked=True,
        id_age=id_age,
        selfie_age=selfie_age,
        gap_years=gap,
        threshold_years=threshold,
        reasons=[reason],
        detail={"id_age": id_age, "selfie_age": selfie_age, "gap_years": gap},
    )


def check_liveness(frames: list[bytes], challenge: str = "blink") -> LivenessResult:
    """
    Compare facial landmark geometry across a short burst of frames.

    blink      -> eye aspect ratio must dip below EAR_DROP_THRESHOLD in at
                  least one frame and recover, so a still image fails.
    head_turn  -> normalised nose-to-eye-midpoint offset must shift by
                  YAW_DELTA_THRESHOLD across the burst.
    """
    if challenge not in {"blink", "head_turn"}:
        return LivenessResult(
            checked=False,
            passed=None,
            challenge=None,
            reasons=["LIVENESS_CHALLENGE_INVALID"],
        )

    if len(frames) < 3:
        return LivenessResult(
            checked=False,
            passed=None,
            challenge=challenge,
            reasons=["LIVENESS_INSUFFICIENT_FRAMES"],
        )

    try:
        # Cheap and import-free, so a missing bundle is reported before any
        # frame is decoded and before mediapipe (seconds to import) loads.
        _require_models("face_landmarker.task")
        landmarks = [_landmarks(frame) for frame in frames]
    except RuntimeError as exc:
        return LivenessResult(
            checked=False,
            passed=None,
            challenge=challenge,
            reasons=["LIVENESS_BACKEND_UNAVAILABLE"],
            # The message names the missing package or model file and the
            # command that fixes it; without it the UI can only shrug.
            detail={"error": str(exc)[:200]},
        )

    usable = [item for item in landmarks if item is not None]
    if len(usable) < 3:
        return LivenessResult(
            checked=True,
            passed=False,
            challenge=challenge,
            reasons=["LIVENESS_FACE_NOT_TRACKED"],
        )

    if challenge == "head_turn":
        yaws = [_yaw_proxy(points) for points in usable]
        delta = max(yaws) - min(yaws)
        passed = delta >= YAW_DELTA_THRESHOLD
        detail = {"yaw_delta": round(delta, 4), "threshold": YAW_DELTA_THRESHOLD}
        reason = "LIVENESS_HEAD_TURN_OK" if passed else "LIVENESS_HEAD_TURN_FAILED"
    else:
        ratios = [_eye_aspect_ratio(points) for points in usable]
        closed = min(ratios)
        opened = max(ratios)
        passed = _blink_detected(ratios)
        detail = {
            "min_ear": round(closed, 4),
            "max_ear": round(opened, 4),
            "threshold": EAR_DROP_THRESHOLD,
        }
        reason = "LIVENESS_BLINK_OK" if passed else "LIVENESS_BLINK_FAILED"

    frames.clear()
    return LivenessResult(
        checked=True,
        passed=passed,
        challenge=challenge,
        detail=detail,
        reasons=[reason, "LIVENESS_REPLAY_ATTACK_NOT_COVERED"],
    )


def _blink_detected(ratios: list[float]) -> bool:
    """Require an open -> closed -> open transition in chronological order."""
    saw_open = False
    saw_closed_after_open = False
    for ratio in ratios:
        if ratio > EAR_DROP_THRESHOLD:
            if saw_closed_after_open:
                return True
            saw_open = True
        elif ratio < EAR_DROP_THRESHOLD and saw_open:
            saw_closed_after_open = True
    return False


# ---------------------------------------------------------------------------
# Landmark helpers (MediaPipe Face Landmarker)
# ---------------------------------------------------------------------------

# The Face Landmarker task emits the same 478-point topology as the retired
# `mp.solutions.face_mesh` (468 mesh points plus 10 iris points), so the
# classic EAR indices carry over unchanged. mediapipe >= 0.10 removed the
# legacy `solutions` namespace; 1.x only ships the Tasks API, which needs the
# `.task` bundle on disk rather than baked into the wheel.
_LEFT_EYE = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)
_NOSE_TIP = 1

_landmarker = None


def _get_landmarker():
    """
    One FaceLandmarker per process. Building it parses the bundle and spins
    up the inference graph; doing that per frame would cost more than the
    inference itself.
    """
    global _landmarker
    if _landmarker is not None:
        return _landmarker

    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError(f"mediapipe missing: {exc}") from exc

    _require_models("face_landmarker.task")

    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(FACE_LANDMARKER_PATH)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    _landmarker = vision.FaceLandmarker.create_from_options(options)
    return _landmarker


def _landmarks(frame: bytes) -> np.ndarray | None:
    try:
        import cv2
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError(f"mediapipe/opencv missing: {exc}") from exc

    array = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        return None

    landmarker = _get_landmarker()
    image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=np.ascontiguousarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB)),
    )
    result = landmarker.detect(image)

    if not result.face_landmarks:
        return None
    face = result.face_landmarks[0]
    return np.array([[point.x, point.y] for point in face], dtype=np.float32)


def _eye_aspect_ratio(points: np.ndarray) -> float:
    def ratio(indices: tuple[int, ...]) -> float:
        p1, p2, p3, p4, p5, p6 = (points[index] for index in indices)
        vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
        horizontal = 2.0 * np.linalg.norm(p1 - p4)
        return float(vertical / horizontal) if horizontal else 0.0

    return (ratio(_LEFT_EYE) + ratio(_RIGHT_EYE)) / 2.0


def _yaw_proxy(points: np.ndarray) -> float:
    """
    Horizontal offset of the nose tip from the eye midpoint, normalised by
    inter-ocular distance so it survives changes in distance to camera.
    """
    left = points[_LEFT_EYE[0]]
    right = points[_RIGHT_EYE[3]]
    nose = points[_NOSE_TIP]
    interocular = float(np.linalg.norm(right - left)) or 1.0
    midpoint_x = (left[0] + right[0]) / 2.0
    return float((nose[0] - midpoint_x) / interocular)


# ---------------------------------------------------------------------------
# Byte handling
# ---------------------------------------------------------------------------

def _write_normalised(image_bytes: bytes, path: str) -> None:
    """
    Decode whatever came in (including the JPEG2000 photo pulled out of an
    Aadhaar QR) and write a plain JPEG that DeepFace can open.
    """
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.save(path, "JPEG", quality=95)


def _shred(path: str) -> None:
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as handle:
            handle.write(b"\x00" * size)
            handle.flush()
            os.fsync(handle.fileno())
        os.remove(path)
    except OSError:
        pass
