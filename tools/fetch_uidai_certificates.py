#!/usr/bin/env python3
"""Fetch the pinned UIDAI Offline e-KYC / Secure QR certificate set."""

from __future__ import annotations

import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aadhaar_qr  # noqa: E402
from config import UIDAI_TRUSTED_CERTIFICATES  # noqa: E402

UIDAI_CERTIFICATE_BASE_URL = (
    "https://backend.uidai.gov.in/get/files/media/document/2026-07"
)
MAX_CERTIFICATE_BYTES = 128 * 1024


def download_certificate(url: str, destination: Path, expected_fingerprint: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary_path = Path(temporary_name)

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VERIFai/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_CERTIFICATE_BYTES + 1)
        if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
            raise ValueError("download was empty or exceeded the certificate size limit")
        temporary_path.write_bytes(payload)

        actual_fingerprint = aadhaar_qr.certificate_fingerprint(str(temporary_path))
        if actual_fingerprint != expected_fingerprint:
            raise ValueError(
                f"fingerprint mismatch: expected {expected_fingerprint}, "
                f"received {actual_fingerprint or 'a non-certificate response'}"
            )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    certificate_dir = ROOT / "certs"
    for filename, fingerprint in UIDAI_TRUSTED_CERTIFICATES:
        url = f"{UIDAI_CERTIFICATE_BASE_URL}/{filename}"
        destination = certificate_dir / filename
        download_certificate(url, destination, fingerprint)
        print(f"OK  {filename}  {fingerprint}")

    print(f"Installed {len(UIDAI_TRUSTED_CERTIFICATES)} pinned certificates in {certificate_dir}")


if __name__ == "__main__":
    main()
