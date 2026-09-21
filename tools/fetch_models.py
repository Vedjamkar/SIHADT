#!/usr/bin/env python3
"""
Fetch the pretrained model files the face pipeline needs.

Why this exists
    Nothing biometric in this repo is trained here. Face match uses DeepFace's
    ArcFace weights, detection uses RetinaFace, the age-gap advisory uses
    DeepFace's age regressor, and liveness uses MediaPipe's Face Landmarker
    bundle. Together that is ~800 MB, two of the files are over GitHub's
    100 MB limit, and DeepFace's default is to download them lazily — inside
    the first request that needs them, into the developer's home directory.
    A fresh clone therefore has no models, and the first selfie upload hangs
    for minutes on hotel Wi-Fi and then fails with a generic error.

    This script makes that explicit and repeatable:
      - every file is listed in `face_match.REQUIRED_MODELS` with its URL,
        SHA-256, and byte size;
      - files land under `models/` in the repo (`config.MODELS_DIR`), which is
        gitignored, so the working tree is the single source of truth;
      - downloads go to a temporary name and are renamed only after the hash
        matches, so a killed download never leaves a half-file that DeepFace
        would mistake for a real one;
      - an existing copy in `~/.deepface/weights` (where DeepFace put it for
        anyone who ran the app before this change) is reused instead of
        re-downloaded.

Usage
    ./.venv/Scripts/python.exe tools/fetch_models.py           # fetch what is missing
    ./.venv/Scripts/python.exe tools/fetch_models.py --check   # report only, exit 1 if missing
    ./.venv/Scripts/python.exe tools/fetch_models.py --verify  # re-hash everything present

Exit codes: 0 all present and verified, 1 something missing or failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Importing face_match does not import deepface/tensorflow; those are lazy.
import face_match  # noqa: E402
from config import MODELS_DIR  # noqa: E402

LEGACY_DEEPFACE_HOME = Path.home() / ".deepface" / "weights"
CHUNK = 1024 * 1024
USER_AGENT = "VERIFai/0.1 (tools/fetch_models.py)"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def verify_file(path: Path, entry: dict) -> str | None:
    """Return None if the file matches the manifest, else a reason string."""
    if not path.is_file():
        return "missing"
    size = path.stat().st_size
    if entry.get("size") is not None and size != entry["size"]:
        return f"size {size} != expected {entry['size']}"
    if entry.get("sha256"):
        actual = sha256_of(path)
        if actual != entry["sha256"]:
            return f"sha256 {actual[:12]}… != expected {entry['sha256'][:12]}…"
    return None


def _install(source: Path, destination: Path, entry: dict, *, move: bool) -> None:
    """
    Verify `source` against the manifest, then place it at `destination` via
    a temporary sibling and an atomic rename.
    """
    problem = verify_file(source, entry)
    if problem:
        raise ValueError(problem)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        if move:
            shutil.move(str(source), str(temp_path))
        else:
            shutil.copyfile(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def download(url: str, destination: Path, entry: dict, *, retries: int = 3) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get("size")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response, temp_path.open(
                "wb"
            ) as sink:
                total = int(response.headers.get("Content-Length") or expected or 0)
                received = 0
                started = time.monotonic()
                # Progress rewrites one line with \r; in a log file that is noise.
                show_progress = sys.stdout.isatty()
                next_report = started + 2.0
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    sink.write(chunk)
                    received += len(chunk)
                    now = time.monotonic()
                    if show_progress and now >= next_report:
                        pct = f"{100 * received / total:5.1f}%" if total else "      "
                        rate = received / max(now - started, 1e-6)
                        print(
                            f"\r    {pct} {_human(received)} / {_human(total)} "
                            f"@ {_human(int(rate))}/s   ",
                            end="",
                            flush=True,
                        )
                        next_report = now + 2.0
            if show_progress:
                print("\r" + " " * 70 + "\r", end="")

            # Verify the temp file in place, then rename. Only a fully
            # verified file ever exists under the final name.
            _install(temp_path, destination, entry, move=True)
            return
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
            print(f"    attempt {attempt}/{retries} failed: {exc}")
            time.sleep(min(2 ** attempt, 10))
        finally:
            temp_path.unlink(missing_ok=True)

    raise RuntimeError(f"could not download {url}: {last_error}")


def fetch(entry: dict, *, check_only: bool, reverify: bool) -> bool:
    relative = entry["path"]
    destination = MODELS_DIR / relative
    label = f"{relative}  ({_human(entry['size'])})" if entry.get("size") else relative

    if destination.is_file():
        if reverify:
            problem = verify_file(destination, entry)
            if problem is None:
                print(f"  ok        {label}")
                return True
            print(f"  corrupt   {label}: {problem}")
            if check_only:
                return False
            destination.unlink()
        else:
            # Size check is cheap; hashing 800 MB on every launch is not.
            size = destination.stat().st_size
            if entry.get("size") is None or size == entry["size"]:
                print(f"  present   {label}")
                return True
            print(f"  corrupt   {label}: size {size} != expected {entry['size']}")
            if check_only:
                return False
            destination.unlink()

    if check_only:
        print(f"  MISSING   {label}")
        return False

    legacy = LEGACY_DEEPFACE_HOME / Path(relative).name
    if legacy.is_file() and relative.startswith(".deepface/"):
        try:
            _install(legacy, destination, entry, move=False)
            print(f"  copied    {label}  <- {legacy}")
            return True
        except ValueError as exc:
            print(f"  ignoring  {legacy}: {exc}")

    print(f"  fetching  {label}\n    from {entry['url']}")
    try:
        download(entry["url"], destination, entry)
    except RuntimeError as exc:
        print(f"  FAILED    {label}: {exc}")
        return False
    print(f"  fetched   {label}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="report what is missing; download nothing"
    )
    parser.add_argument(
        "--verify", action="store_true", help="re-hash files already present"
    )
    parser.add_argument(
        "--print-hashes",
        action="store_true",
        help="print sha256 and size of every present file (to update the manifest)",
    )
    args = parser.parse_args(argv)

    print(f"Model directory: {MODELS_DIR}")
    if args.print_hashes:
        for entry in face_match.REQUIRED_MODELS:
            path = MODELS_DIR / entry["path"]
            if path.is_file():
                print(f"{entry['path']}\n  sha256 {sha256_of(path)}\n  size   {path.stat().st_size}")
            else:
                print(f"{entry['path']}\n  missing")
        return 0

    ok = True
    for entry in face_match.REQUIRED_MODELS:
        ok &= fetch(entry, check_only=args.check, reverify=args.verify)

    if ok:
        print("All face-pipeline model files are present.")
        return 0
    if args.check:
        print("Some model files are missing. Run: python tools/fetch_models.py")
    else:
        print(
            "Some model files could not be fetched. Check the network and retry; "
            "the face-match, age-gap, and liveness checks stay unavailable until then."
        )
    return 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
