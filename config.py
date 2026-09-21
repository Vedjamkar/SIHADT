"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# DeepFace and the RetinaFace package both resolve their weight cache as
# `$DEEPFACE_HOME/.deepface/weights`, defaulting to the user's home directory.
# That default is why a fresh clone has no models: ~260 MB sits in one
# teammate's %USERPROFILE% and nowhere else. Pointing it at the repo makes
# `models/` the single place weights live, so `tools/fetch_models.py` can fill
# it, `/health` can report on it, and the launcher can check it before the
# first face request instead of stalling that request on a download.
# Must run before anything imports deepface; config is imported first everywhere.
MODELS_DIR = Path(os.getenv("DEEPFACE_HOME") or ROOT / "models").resolve()
os.environ["DEEPFACE_HOME"] = str(MODELS_DIR)
WEIGHTS_DIR = MODELS_DIR / ".deepface" / "weights"


UIDAI_TRUSTED_CERTIFICATES = (
    (
        "uidai_offline_publickey_2026.cer",
        "e0304b9e61ee3640ecddae2db4b617f2e2678f57dbc2826c2f86ac5c04f277df",
    ),
    (
        "uidai_offline_publickey_17022026.cer",
        "00573c692cf04fbee113ae5fd52f2a654d361bf8ee4d06c46008906b36df8169",
    ),
    (
        "uidai_offline_publickey_26022021.cer",
        "e0f0f869d32efc7e80fae2223717a56dcf8b616f820b542a49e5bd5abf1c0f7d",
    ),
    (
        "uidai_offline_publickey_29032019.cer",
        "e0f5596d2c48e19f9cc184bccde7129e2d8987f905c73b87d1851c35c622d852",
    ),
    (
        "uidai_offline_publickey_26022019.cer",
        "35575c63c72106e803511004f94bfda54952b2cf2184c3ce1aad61f1964c58d0",
    ),
    (
        "uidai_12_06_18_cer.cer",
        "49e298532243ce28e2633a7e4f403d9ca78cbfda8b3bbde70324837273ba4d31",
    ),
    (
        "uidai_prod_cdup.cer",
        "fcf31a3f89211615ebd5d449ac33d8d381f654d2e2d15037d5cc8d4aeb72f836",
    ),
)


@dataclass(frozen=True)
class Settings:
    uidai_cert_dir: str = os.getenv("UIDAI_CERT_DIR", "certs")
    uidai_cert_path: str = os.getenv("UIDAI_CERT_PATH", "")

    # The default trust set above is always pinned. These two variables retain
    # the single-certificate override used by mock and targeted tests;
    # `python tools/mock_pki.py init` prints the matching mock fingerprint.
    uidai_cert_fingerprint: str = os.getenv("UIDAI_CERT_FINGERPRINT", "")
    database_path: str = os.getenv("AUDIT_DB_PATH", "audit.sqlite3")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", 8 * 1024 * 1024))
    max_image_pixels: int = int(os.getenv("MAX_IMAGE_PIXELS", 16_000_000))
    max_face_frames: int = int(os.getenv("MAX_FACE_FRAMES", 30))
    max_face_burst_bytes: int = int(
        os.getenv("MAX_FACE_BURST_BYTES", 32 * 1024 * 1024)
    )

    # Your plan says demo data comes only from consenting teammates. That works
    # as a rule on a whiteboard and fails the moment someone tests with a
    # cousin's card at 2am. The face-match endpoint requires an explicit
    # consent subject and refuses without one, so the rule lives in the code.
    require_consent_subject: bool = (
        os.getenv("REQUIRE_CONSENT_SUBJECT", "true").lower() == "true"
    )

    # Comma-separated list of teammates who have given consent, e.g.
    # CONSENT_SUBJECTS="vishu,priya,arjun"
    consent_subjects: tuple[str, ...] = tuple(
        item.strip().lower()
        for item in os.getenv("CONSENT_SUBJECTS", "").split(",")
        if item.strip()
    )

    # On-screen redaction of ID numbers, per your constraints. Server-side, so
    # a frontend bug cannot leak a real number into a screenshot.
    redact_identifiers: bool = (
        os.getenv("REDACT_IDENTIFIERS", "true").lower() == "true"
    )

    # Aadhaar is reissued at 5 and 15 with a fresh photo, and even an adult
    # photo ages over a document's lifetime. A large apparent gap between the
    # ID photo and the live selfie is a real reason a genuine face-match can
    # come back weak — it is reported as advisory context, never as a forgery
    # signal, and never overrides the match distance itself.
    age_gap_advisory_years: int = int(os.getenv("AGE_GAP_ADVISORY_YEARS", 12))


settings = Settings()
