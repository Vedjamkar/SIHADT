# Setup — getting it running

Windows-first, because that is what the team is on. Linux/macOS notes at the end.

> **The old README's setup section is wrong in one important way.** It says
> `uvicorn app.main:app`. There is no `app/` package — the repo is flat. The correct
> command is `uvicorn main:app`. See §6 for the full list of corrections.

---

## 1. Python

Use **Python 3.12**. Not 3.13 or 3.14 — the face-match stack (mediapipe, tf-keras) does not
have wheels for them yet, and you will lose an evening to build errors.

Check what you have:

```bash
py -0
```

Create the virtual environment with 3.12 explicitly:

```bash
py -V:3.12 -m venv .venv
```

Activate it:

```bash
.venv\Scripts\activate
```

(Git Bash: `source .venv/Scripts/activate`. PowerShell: `.venv\Scripts\Activate.ps1` — if that
is blocked, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.)

You will know it worked when your prompt is prefixed with `(.venv)`.

---

## 2. Python packages

```bash
pip install -r requirements.txt
```

Install in two stages if you want to be able to work before the heavy machine-learning
packages finish. The core stack is enough for Aadhaar QR, PAN, marksheet, ELA, and the whole
API surface:

```bash
pip install fastapi uvicorn[standard] python-multipart cryptography pillow numpy opencv-python-headless pyzbar pytesseract pymupdf
```

Then, separately, the face stack (large — pulls TensorFlow):

```bash
pip install deepface tf-keras mediapipe
```

### Model files (not in git)

The face stack is code only. The pretrained weights it runs — ArcFace, RetinaFace,
DeepFace's age regressor, and MediaPipe's Face Landmarker bundle — total ~800 MB and are
**not in the repository** (two of them are over GitHub's 100 MB per-file limit). Fetch them
once:

```bash
python tools/fetch_models.py
```

They land in `models/` (gitignored; see [`models/README.md`](../models/README.md)), each
checked against the SHA-256 pinned in `face_match.REQUIRED_MODELS`. `Launch VERIFai.cmd`
runs this step for you. Until it has succeeded, `/health` reports `face_models_ready: false`
and the face-match, age-gap, and liveness checks return an error naming the command to run —
they no longer try to download inside the request. Document checks work regardless.

If someone on the team already ran an older build, their copies in `%USERPROFILE%\.deepface\weights`
are reused instead of re-downloaded.

---

## 3. Native binaries — the part that actually breaks

Two Python packages are thin wrappers around native programs. Installing the Python package
does **not** install the program.

### Tesseract (needed for passport, PAN, and marksheet OCR)

`pip install pytesseract` gives you a wrapper, not the OCR engine. On Windows, get the
installer from the UB-Mannheim build (the de-facto standard Windows distribution of Tesseract),
install it, then either add its folder to `PATH` or point at it explicitly:

```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Verify:

```bash
tesseract --version
```

If that command is not found, OCR will fail at runtime with
`TesseractNotFoundError` — the API starts fine and only the passport, PAN, and marksheet
endpoints break. **This is the current state on at least one team machine.**

### zbar (needed for QR decoding)

`pyzbar` normally bundles the zbar DLL on Windows. If you get
`FileNotFoundError: Could not find module 'libzbar-64.dll'`, install the
**Visual C++ Redistributable for Visual Studio 2013** — that is the actual missing piece, and
the error message does not say so.

---

## 4. UIDAI certificates — required for the showpiece

**Nothing cryptographic works without these.** Certificates do not ship with the repo.

Download the production certificates listed under Offline e-KYC and Secure QR Code on
[UIDAI's current certificate page](https://uidai.gov.in/en/data-and-download). Keep their
official filenames under `certs/`:

`uidai_offline_publickey_2026.cer`, `uidai_offline_publickey_17022026.cer`,
`uidai_offline_publickey_26022021.cer`, `uidai_offline_publickey_29032019.cer`,
`uidai_offline_publickey_26022019.cer`, `uidai_12_06_18_cer.cer`, and
`uidai_prod_cdup.cer`.

The expected SHA-256 fingerprints are pinned in `config.py`. The app loads only those exact
entries, so placing another certificate in the directory does not add it to the trust set.
Historical keys matter because a newly downloaded PDF can still carry a QR signed under an
older UIDAI key.

Fetch and fingerprint-check the complete set from UIDAI:

```bash
python tools/fetch_uidai_certificates.py
```

For a deliberate single-certificate or mock test, override both values:

```bash
set UIDAI_CERT_PATH=C:\path\to\uidai_signing.cer
set UIDAI_CERT_FINGERPRINT=the_64_character_sha256_fingerprint
```

> **Read this before you lose a day.** The certificate you find most easily by searching —
> `uidai_auth_stage.cer` — is the **staging/test** certificate. It will **not** verify a real
> production Aadhaar card. Production cards are signed with rotating production keys. If a card
> everyone is certain is genuine fails verification, check which certificates are loaded
> *before* concluding the code is broken.

Without any certificate the system does **not** silently pass documents. It reports
`UIDAI_CERT_NOT_CONFIGURED` and returns `UNVERIFIABLE` for every Aadhaar — correct behaviour,
but it means the demo shows nothing.

---

## 5. Consent — the app refuses to run face-match without it

The plan's rule "demo data only from consenting teammates" is enforced in code, not on a
whiteboard. `/verify/face` and `/verify/aadhaar-full` return **403** unless a
`consent_subject` is supplied that appears in this list:

```bash
set CONSENT_SUBJECTS=ved,prayag,personC,personD
```

This is deliberate and should not be removed. If you are demoing, set it; if you are testing
someone's ID who has not agreed, the correct outcome is the 403 you are getting.

---

## 6. Run it

```bash
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000/docs** — FastAPI generates an interactive page where you can
upload files to each endpoint without writing any frontend code. Use this to test everything
before the UI exists.

Health check: **http://localhost:8000/health** — tells you whether the certificate loaded,
whether consent enforcement is on, and whether the face-pipeline model files are present
(`face_models_ready`, with `face_models_missing` listing what `tools/fetch_models.py` still
has to fetch).

### Corrections to the old README

| Old README says | Reality |
|---|---|
| `uvicorn app.main:app` | `uvicorn main:app` — repo is flat, there is no `app/` package |
| `python tests/test_core.py` before demo day | **That file does not exist.** There are no tests. |
| `sudo apt-get` / `brew` only | Team is on Windows; see §3 |

---

## 7. Linux / macOS

```bash
sudo apt-get install -y libzbar0 tesseract-ocr     # Debian/Ubuntu
brew install zbar tesseract                        # macOS

python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: attempted relative import with no known parent package` | You are on a commit before the import fix | Use branch `fix/runnable` or later |
| `ModuleNotFoundError: No module named 'pymupdf'` | Old `requirements.txt` | `pip install pymupdf` — now pinned in requirements |
| `TesseractNotFoundError` | Tesseract engine not installed | §3 |
| `Could not find module 'libzbar-64.dll'` | Missing VC++ 2013 redistributable | §3 |
| Every Aadhaar returns `UNVERIFIABLE` | No certificate loaded | §4 — check `/health` |
| A genuine card fails signature verification | Staging certificate loaded instead of production | §4 |
| `403` on face endpoints | `CONSENT_SUBJECTS` not set, or subject not in it | §5 — this is intended behaviour |
| mediapipe / tf-keras will not install | Python 3.13+ | §1 — use 3.12 |
| Face match returns `FACE_MATCH_ERROR` with `ModelFilesMissing`, or `/health` says `face_models_ready: false` | Model files not fetched | §2 — `python tools/fetch_models.py` |
| Liveness returns `LIVENESS_BACKEND_UNAVAILABLE` naming `face_landmarker.task` | Same — the MediaPipe bundle is fetched by the same script | §2 |
| `module 'mediapipe' has no attribute 'solutions'` | mediapipe 1.x removed the legacy API; `face_match.py` now uses the Tasks API | Pull latest; make sure `models/face_landmarker.task` exists |
