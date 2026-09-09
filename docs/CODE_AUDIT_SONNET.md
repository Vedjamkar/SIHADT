# Mechanical Code Audit — SiH_Verif backend

Scope: every file in the repo root (`main.py`, `aadhaar_qr.py`, `verhoeff.py`, `pan.py`,
`marksheet.py`, `ela.py`, `face_match.py`, `ocr.py`, `verdict.py`, `store.py`,
`config.py`, `README.md`, `requirements.txt`) was read in full. No files outside
this list exist in the repository (confirmed by a recursive listing — the only
other content is `.git/`). This is a factual, file-by-file audit only: no
redesign, no threat modelling. Every behavioural claim below cites `file:line`.
Where source alone could not settle a question, that is stated explicitly
rather than guessed.

---

## 0. The one fact that governs everything else

The repository has **no package structure**. `main.py` imports:

```
main.py:30   from .config import settings
main.py:31   from .services import aadhaar_qr, ela, face_match, marksheet, ocr, pan, verhoeff
main.py:32   from .store import AuditStore
main.py:33   from .verdict import REASON_TEXT, assess
```

These are relative imports, which require `main.py` to live inside a Python
package, and `from .services import ...` additionally requires a `services`
sub-package. Neither exists: there is no `app/` directory, no `__init__.py`
anywhere in the tree, and no `services/` directory — `aadhaar_qr.py`, `ela.py`,
`face_match.py`, `marksheet.py`, `ocr.py`, `pan.py`, `verhoeff.py` sit directly
in the repo root next to `main.py` (confirmed by directory listing). The
README's own start command, `uvicorn app.main:app --reload --port 8000`
(README.md:19), presupposes exactly the package layout that is missing.

**As checked out, the application cannot be imported, let alone started.**
This is not a dependency problem and is independent of anything in section 3 —
fixing it means moving files into the layout the code already assumes
(`app/__init__.py`, `app/main.py`, `app/services/__init__.py`, etc.) and is a
20-minute mechanical fix, but it means the repo has evidently never been run
from a clean checkout in this state.

---

## 1. Inventory

| File | Lines | What it actually does | Status |
|---|---:|---|---|
| `main.py` | 574 | FastAPI app: 8 endpoints (aadhaar, aadhaar-full, pan, marksheet, face, dashboard/history, dashboard/summary, reasons, health), request-level validation, wires services together, builds response envelope. | **PARTIAL** — logic is real and non-trivial, but the module cannot be imported at all in the current file layout (see §0), and it imports a dependency (`pymupdf`, line 25) that is absent from `requirements.txt`. |
| `aadhaar_qr.py` | 518 | Multi-strategy QR image extraction (pyzbar + OpenCV, multiple preprocessing passes), V1 (legacy XML, unsigned) and V2 (Secure QR: bigint→bytes→gzip→fields→JPEG2000 photo→signature) parsing, RSA-PKCS1v15/SHA-256 signature verification, certificate loading. | **WORKING** (verified by static trace — no test harness in repo to execute it; see §2 for the one operational gap: the certificate file it needs to do anything useful is not shipped). |
| `verhoeff.py` | 82 | Verhoeff (D5 dihedral group) checksum: `validate`, `check_digit`, `validate_aadhaar_number`. | **WORKING** — verified below by actually running the tables (see §2.1). This is the one module in the repo I could independently execute and confirm correct, because it has zero external dependencies. |
| `pan.py` | 98 | PAN regex/structural validation (`AAAAA9999A`), holder-type lookup, weak name-initial cross-check. Explicitly disclaims any cryptographic/official check (pan.py:11-16). | **WORKING**, and honestly scoped — the module's own docstring is more accurate about its limits than the README's summary table implies. |
| `marksheet.py` | 567 | OCR-line fuzzy-matching to find 5 user-selected subjects, mark extraction by regex/position heuristics, selected-subject total/percentage computation, range check (`obtained > maximum`), a separate row-spacing/"baseline" heuristic. | **PARTIAL, with a dead headline feature.** The module tracks `printed_total` and `printed_percentage` fields (marksheet.py:62-63) and defines `TOTAL_CONSISTENT`, `TOTAL_MISMATCH`, `PERCENTAGE_MISMATCH` reason codes (marksheet.py:38-40) that are wired into the "structural problem" set (marksheet.py:460-467) and given display text in `verdict.py` (verdict.py:94-96) — but nothing in `analyse()` ever reads a printed total off the document or assigns those two fields or emits those three reason codes. Grepped the whole file: no assignment to `printed_total`/`printed_percentage` exists anywhere. This is precisely the check the README calls out as the standout catch ("Subject marks that do not sum to the printed total is a real, explainable catch... what to put on screen when a judge says 'show it catching a fake, live'", README.md:82-84). **It is not implemented.** What *is* implemented is: selected-subject total/percentage arithmetic (which is just addition, not a consistency check against anything printed) and an out-of-range check. |
| `ela.py` | 157 | JPEG-quality-90 re-encode, pixel-difference heatmap, 32×32 block-mean z-score outlier flagging. | **WORKING** as a heuristic, exactly as scoped by its own docstring (ela.py:15-29), which is unusually candid that this is the weakest signal in the app. All thresholds are hardcoded (see §2.3). |
| `face_match.py` | 278 | DeepFace (`ArcFace` model, `retinaface` detector, cosine distance) 1:1 face comparison; MediaPipe Face Mesh landmark-based blink/head-turn liveness; temp-file zero-and-unlink cleanup. | **WORKING** as a heuristic biometric check, correctly scoped (its docstring states plainly that the liveness check does not defeat video replay, face_match.py:23-30). Depends on `deepface`, `mediapipe`, `tf-keras` at runtime (see §3). |
| `ocr.py` | 582 | Tesseract-primary / EasyOCR-fallback text extraction, PAN-specific multi-pass preprocessing + OCR-error correction + candidate scoring, Aadhaar/PAN/date/year regex extraction. | **WORKING**, but degrades silently: if Tesseract is not on `PATH` and `easyocr` is not installed (it is commented out of `requirements.txt`, requirements.txt:20), `extract_text` returns `engine="unavailable"` and empty text with no exception raised to the caller (ocr.py:444-470) — every downstream check (Aadhaar-number-from-OCR, PAN, marksheet subject matching) then fails for a reason the API response never states. |
| `verdict.py` | 239 | Three-tier (cryptographic > structural > heuristic) verdict resolution, reason-code catalogue, identity-binding axis. | **WORKING**, well-designed, and the most polished file in the repo — but see §2.5 for a latent tier-lookup inconsistency and one genuinely dead reason code. |
| `store.py` | 144 | SQLite schema and CRUD for the audit trail (verdict, binding, reason codes, face distance, timestamps). No image, no embedding, no raw ID number column. | **WORKING**, and its no-PII claim is accurate against the schema (store.py:24-39). |
| `config.py` | 38 | `Settings` dataclass: DB path, upload size cap, consent enforcement, redaction flag, cert path — mostly via `os.getenv`. | **WORKING with one bug** — `uidai_cert_path` (config.py:11) is declared without a type annotation, so it is *not* a dataclass field (see §2.2); every other setting is env-configurable, this one is hardcoded. |
| `README.md` | 187 | Setup instructions, endpoint table, design rationale, judge Q&A. | Internally consistent and well-written, but makes claims not reflected in the code: it instructs `python tests/test_core.py` (README.md:26) — **no `tests/` directory exists anywhere in the repo**; it does not mention that `pymupdf` must be installed even though `main.py` imports it unconditionally; and its description of marksheet "total mismatch" detection (README.md:82-84) describes code that is not there (see `marksheet.py` row above). |
| `requirements.txt` | 25 | Pinned dependency list (`==` throughout — not unpinned, contrary to a common failure mode in repos like this). | Missing `pymupdf`/`PyMuPDF`, which `main.py` imports unconditionally at module scope (main.py:25). Everything actually imported by `aadhaar_qr.py`, `verhoeff.py`, `pan.py`, `ela.py`, `store.py`, `config.py`, `verdict.py` is present. `opencv-python` (full) is not listed but `opencv-python-headless` is, and `cv2` import sites (aadhaar_qr.py:154, aadhaar_qr.py:223; face_match.py:209) only need the headless API used here, so that substitution is fine. |

No file in this repo is a pure STUB (empty body / `pass` / `NotImplementedError`) or obviously DEAD (unused module) — the dead code found is at the *statement* level, inside otherwise-real modules (marksheet's missing total-check, verdict's unreachable reason code), not whole files.

---

## 2. Correctness defects

### 2.1 `verhoeff.py` — tables and algorithm verified correct

I extracted the module (it has no external dependencies, so it could be
exercised directly without installing anything) and ran it:

- `check_digit("236")` → `3`. `236` + check digit `3` = `2363`, which is the
  standard published Verhoeff worked example, and `validate("2363")` → `True`.
- Built a synthetic 12-digit number that satisfies `validate_aadhaar_number`'s
  own rules (12 digits, leading digit not `0`/`1`): base `23456789012`,
  computed check digit `4` → full number `234567890124`.
  `validate_aadhaar_number("234567890124")` → `(True, "AADHAAR_VERHOEFF_OK")`.
- Flipped a single interior digit (`234568890124`) →
  `validate_aadhaar_number(...)` → `(False, "AADHAAR_VERHOEFF_FAILED")`.

So the D-table (verhoeff.py:15-26), P-table (verhoeff.py:29-38), and inverse
table (verhoeff.py:41) are correct, and `validate()` (verhoeff.py:49-57) is a
real check, not a stub that always returns `True`. This is the one module in
the repo whose "WORKING" status is backed by an actual execution, not just
static reading.

### 2.2 `config.py:11` — `uidai_cert_path` silently falls outside the dataclass

```python
@dataclass(frozen=True)
class Settings:
    uidai_cert_path = "certs/uidai_signing.cer"   # config.py:11 — no type annotation
    database_path: str = os.getenv(...)            # config.py:12
    ...
```

Every other field on `Settings` carries a type annotation and reads its value
from `os.getenv(...)`. `uidai_cert_path` has no annotation, so Python's
`dataclasses` machinery does not register it as a field at all — it becomes an
ordinary class attribute. Practical effects: (a) it cannot be overridden by an
environment variable the way every sibling setting can, unlike the pattern the
rest of the file establishes; (b) it is invisible to anything that introspects
`Settings` fields (`dataclasses.fields(settings)` will not list it). It still
works as a constant string, so this does not crash anything, but it is an
inconsistency against the file's own convention and the one setting most
worth making deployment-configurable (the UIDAI cert path) is the one that
cannot be.

### 2.3 `ela.py` — thresholds are hardcoded magic numbers, exactly as asked to check

```
ela.py:41   RESAVE_QUALITY = 90
ela.py:42   BLOCK_SIZE = 32
ela.py:43   FLAG_SIGMA = 2.5          # how many std-devs above mean a block must sit
ela.py:44   MIN_FLAGGED_FRACTION = 0.004  # ignore single-block specks
```

All four are module-level literals, not read from `config.py` or any external
calibration file, and the module's own docstring (ela.py:15-29) states outright
that these have not been validated against a labelled dataset and that a
forger who re-encodes the whole document defeats the technique in one step.
This is honestly documented, but it is still four unvalidated magic numbers
driving a signal that feeds `NEEDS_REVIEW` verdicts (verdict.py:215-216).

### 2.4 `aadhaar_qr.py` — traced in full against the described pipeline

- Big-integer → bytes: `big_integer.to_bytes(byte_length, "big")` (aadhaar_qr.py:341-342).
- Decompression: gzip-magic check first, then three zlib `wbits` variants as
  fallback, then pass-through (aadhaar_qr.py:300-309).
- Field splitting deliberately avoids a blind `data.split(b"\xff")` because the
  embedded JPEG2000 photo legitimately contains `0xFF` bytes in its marker
  segments — it scans forward for exactly the delimiters it needs and stops
  (aadhaar_qr.py:312-332), which is the correct approach and matches the
  module's own explanation.
- Signature location: **last 256 bytes** of the decompressed payload
  (`SIGNATURE_LENGTH = 256`, aadhaar_qr.py:48; `signature = data[-SIGNATURE_LENGTH:]`,
  aadhaar_qr.py:352). Signed region is everything before it
  (aadhaar_qr.py:351).
- Hash/padding: `hashes.SHA256()` with `padding.PKCS1v15()`
  (aadhaar_qr.py:360-365) — this is SHA-256-with-RSA PKCS#1 v1.5, as documented.
- Certificate loading and fail behaviour: `load_uidai_public_key`
  (aadhaar_qr.py:466-489) tries PEM cert, DER cert, then bare PEM public key,
  and returns `None` on any failure (including the file simply not existing —
  it catches `OSError` from the `open()` call, aadhaar_qr.py:475-479). When the
  key is `None`, `_parse_v2` sets `signature_verified = None` and appends
  reason `UIDAI_CERT_NOT_CONFIGURED` (aadhaar_qr.py:355-357) — it does **not**
  fail open (it never returns `signature_verified = True` when there is no
  key to check against). This is correct, fail-closed behaviour.
  - **However**: there is no `certs/` directory and no `.cer`/`.pem` file
    anywhere in this repository, and `config.py:11` hardcodes the path to
    `certs/uidai_signing.cer` with no fetch script or documented download
    step beyond a prose instruction in the README ("fetch from UIDAI, do not
    copy from a random repo", README.md:15-16, with no URL given). As shipped,
    `UIDAI_KEY` (main.py:50) will always be `None`, `/health` will always
    report `uidai_certificate_loaded: false`, and — per `verdict.py`'s tier
    logic — every single Aadhaar verification will resolve to `UNVERIFIABLE`
    rather than ever reaching `GENUINE_SIGNED` or `FORGED_SIGNATURE`. This
    matches what the README itself warns about (README.md:22-24), so it is
    not a hidden bug, but it does mean the headline feature is inert out of
    the box and there is no committed fixture/test certificate to demonstrate
    it either.
- JPEG2000 photo extraction: the photo segment is sliced out by counting
  backwards from the signature (subtracting `trailing_hashes * HASH_LENGTH`,
  aadhaar_qr.py:404-411) and returned as raw bytes on
  `AadhaarQRResult.photo_jp2` (aadhaar_qr.py:89, aadhaar_qr.py:424). It is
  used later for face-matching (main.py:225-227) and never serialized into
  any API response or the store — only a boolean `id_photo_available`
  (main.py:168) reaches the client, consistent with the module's own
  privacy claims.

### 2.5 `verdict.py` — a latent tier-lookup inconsistency, and one dead reason code

Two different places compute a reason code's tier with two different
fallback behaviours:

```
verdict.py:200-204   heuristic_flags = [
                          code for code in codes
                          if TIER_OF_REASON.get(code) is Tier.HEURISTIC   # no default -> None for unknown codes
                      ]
verdict.py:179-184   def _describe(code: str) -> dict:
                          return {
                              "code": code,
                              "tier": TIER_OF_REASON.get(code, Tier.HEURISTIC).value,  # defaults unknown codes to "heuristic"
                              ...
```

For any reason code not present in `TIER_OF_REASON` (built at
verdict.py:126-152), `_describe` will *display* it with `tier: "heuristic"` in
the API response, while `assess()`'s own verdict computation silently treats
it as **no tier at all** and excludes it from influencing the verdict. Today
this only affects `UIDAI_CERT_NOT_CONFIGURED`, and the net effect happens to
be correct (an Aadhaar check with a missing cert and nothing else wrong
resolves to `UNVERIFIABLE`, matching the README's claim at README.md:22-24) —
I verified this by tracing `assess()` by hand for that exact code path. But
this is fragile: any reason code added later without an entry in
`TIER_OF_REASON` will be silently excluded from the verdict decision while
still being labelled "heuristic" for the reviewer, which is a foot-gun for
whoever extends this file next.

Separately, `IDENTITY_NOT_CHECKED` has display text (verdict.py:115) but is
never appended to any `codes` list anywhere in the repository (confirmed by
grep across all seven files) — it is dead.

### 2.6 `main.py` — endpoint-level issues

- **Unconditional import of an unlisted dependency.** `import pymupdf`
  (main.py:25) is a *module-level* import, not deferred into the
  PDF-handling branch. `pymupdf` does not appear in `requirements.txt` at
  all. Following the README's own install instructions
  (`pip install -r requirements.txt`, README.md:12) will not install it, and
  the entire application — every endpoint, not just `/verify/marksheet` —
  will fail to import.
- **Frame-count validation runs after the expensive work it's meant to
  guard, in one endpoint but not the other.** In `/verify/aadhaar-full`:
  ```
  main.py:233   liveness = face_match.check_liveness(list(frame_bytes), challenge="blink")
  main.py:236-239  match = face_match.compare_faces(face_source, frame_bytes[len(frame_bytes)//2])
  main.py:242   ela_result = ela.analyse(front_bytes)
  main.py:243-247  if len(frame_bytes) < 3: raise HTTPException(400, ...)
  ```
  The "at least 3 frames" check fires only *after* liveness detection, face
  comparison, and ELA have already run on the (too-few) frames. Contrast with
  `/verify/face`, where the same check correctly runs first
  (main.py:503-509, before `check_liveness`/`compare_faces` are called at
  main.py:509-510). This does not crash (both `check_liveness` and
  `compare_faces` degrade gracefully with fewer frames) and does not leak
  data (the request is still rejected with 400 before `store.record` is
  called), but it means every under-supplied `/verify/aadhaar-full` request
  pays for a full DeepFace + MediaPipe + ELA pass before being told the
  request was invalid — wasted compute, and a real cost on the demo machine's
  only GPU/CPU budget.
- **No exception handling around file-format-sensitive calls.** None of the
  five `POST /verify/*` handlers wrap `ocr.extract_text`, `ela.analyse`,
  `aadhaar_qr.verify_aadhaar_image`, or `face_match.compare_faces` in
  `try/except`. All of these call `PIL.Image.open` on user-supplied bytes
  internally; a corrupted or non-image upload that passes the empty/size
  checks in `read_upload` (main.py:57-63) but fails to decode will raise an
  unhandled `PIL.UnidentifiedImageError` (or similar) that FastAPI will turn
  into a bare 500 response with no actionable message — there is no global
  exception handler registered on `app` anywhere in `main.py`.
- **Upload cleanup**: `main.py` itself never writes uploaded bytes to disk —
  every `UploadFile` is read into memory once via `read_upload`
  (main.py:57-63) and only `bytes` objects are passed onward. The one
  exception is `face_match.compare_faces`, which does write to a temp
  directory and removes it in a `finally` block with a zero-and-unlink shred
  step (face_match.py:76-128) — this part matches its documented privacy
  claim. Note that Starlette's `UploadFile` itself may spool large uploads to
  a temporary file internally before `.read()` is called; that lifecycle is
  framework-managed and closed automatically at the end of the request, not
  something `main.py` controls or needs to control.

### 2.7 `face_match.py` — threshold direction checked, found correct (contrary to the concern flagged in scope)

`compare_faces` uses `distance_metric="cosine"` (face_match.py:90) and DeepFace
returns a **cosine distance** (0 = identical, larger = more different), not a
similarity score. The match rule is:

```
face_match.py:98   is_match=distance <= MATCH_THRESHOLD,
```

`MATCH_THRESHOLD = 0.68` (face_match.py:46) is documented in the module as
"DeepFace's own tuned default" for ArcFace + cosine distance
(face_match.py:42-43), and the comparison direction (`distance <= threshold`
→ match) is the correct direction for a *distance* metric — lower distance
means more similar, so this is not inverted. `similarity` (face_match.py:97,
`1 - distance` clamped at 0) is computed only for display and is not used in
the match decision (`is_match` is computed from `distance`, not from
`similarity`), so there is no mixed-direction bug here either. I could not
verify the numeric value `0.68` itself against DeepFace's source (that would
require inspecting the installed `deepface` package, which is not present in
this environment), so I am not vouching for whether `0.68` is in fact
DeepFace's current default for this exact model/metric pairing — only that
the code applies whatever threshold it has in the mathematically correct
direction.

Liveness: `check_liveness` measures (a) blink, via eye-aspect-ratio dipping
below `EAR_DROP_THRESHOLD` and recovering across a burst of frames
(face_match.py:176-185), and (b) head-turn, via normalised horizontal nose
displacement relative to inter-ocular distance
(face_match.py:169-174, 239-249) — both computed from MediaPipe Face Mesh
landmarks (face_match.py:207-226). It does not do depth sensing, texture
analysis, or any trained presentation-attack-detection model, and the code
says so itself, appending `LIVENESS_REPLAY_ATTACK_NOT_COVERED` to every
successful liveness result unconditionally (face_match.py:193).

### 2.8 `store.py` — what is persisted, confirmed against the schema

```
store.py:24-36   CREATE TABLE checks (
                     id, created_at, doc_type, qr_version, verdict, decided_by,
                     binding, reason_codes, advisory_codes, face_distance, liveness
                 )
```

No column can hold an image, an embedding, a full Aadhaar/PAN number, a name,
or any other direct identifier — `reason_codes`/`advisory_codes` are JSON
arrays of the short string codes defined in `verdict.py`, and `face_distance`
is a rounded float (`round(face_distance, 2)`, store.py:89). This matches the
file's own claim (store.py:1-13) and `README.md`'s privacy section
(README.md:129-131). The database itself is a plain SQLite file at
`settings.database_path` (default `audit.sqlite3`, config.py:12), written to
the process's working directory with no encryption — reasonable for a local
demo, but note this if the machine used for the demo is shared.

### 2.9 `marksheet.py` — mark-extraction is positional-heuristic, not layout-verified

`_extract_subject_marks` (marksheet.py:172-224) infers which numbers on an
OCR'd line are theory/internal/total purely by *how many* numbers were found
on that line (4+, exactly 3, exactly 2, or 1), assuming a fixed CBSE-style
layout (marksheet.py:178-190). There is no column-position/coordinate
verification (e.g. from Tesseract's word-box output) — it is a pure
count-based heuristic over whatever `_extract_numbers_from_line` regex-finds
(`\b\d{1,3}\b`, marksheet.py:168), so any stray 1-3 digit number OCR'd on the
same line (page number, roll number fragment, a stray printed artefact) will
silently shift which numbers are treated as theory/internal/total. This is
consistent with the module's own framing as "internal-consistency, not
official verification" (marksheet.py:15), but it is worth being precise that
"internal consistency" here does not include any check that the extracted
marks are even the right numbers — see §1's finding that the one check which
would catch that (comparing against a printed total) is not implemented.

---

## 3. Runnability on Windows 11 / Python 3.12

I did not run `pip install` (per instructions) and did not attempt to start
the server, since §0 already establishes it cannot start as checked out. What
follows is a static reading of `requirements.txt` against every `import` in
the seven service modules plus `main.py`, plus what I could confirm from a
locally available Python.

This machine has Python 3.11.15, 3.14.3, and a pip pointing at a 3.12
install; I did not find a bare "3.12.x" interpreter to invoke directly, but
`pip --version` confirms a Python 3.12 environment exists on this box
(`pip 25.0.1 ... (python 3.12)`).

**Blockers that are certain from source alone, independent of any package's
Windows/Python-3.12 support:**

1. **No package layout** (§0) — `ModuleNotFoundError`/`ImportError` on
   `uvicorn app.main:app` regardless of what is installed, because there is
   no `app` package on disk.
2. **`pymupdf` missing from `requirements.txt`** but imported unconditionally
   at `main.py:25` — `ModuleNotFoundError: No module named 'pymupdf'` even
   after `pip install -r requirements.txt`.
3. **No `certs/` directory and no UIDAI certificate file** — the app will
   still start (once §0/§1 are fixed) and `/health` will work, but every
   Aadhaar verification is inert (§2.4) until someone sources a real
   certificate; there is nothing to `pip install` that fixes this.
4. **`tests/test_core.py` does not exist** — the README's own
   pre-demo smoke test (README.md:26-27) cannot be run.

**Native/system-binary dependencies named in the task, checked against this
repo's actual usage:**

- **`pyzbar` (pyzbar.pyzbar.decode, aadhaar_qr.py:127, 214)** needs the
  ZBar shared library. On Linux this means a separate `apt-get install
  libzbar0`; the PyPI Windows wheel for `pyzbar` has historically bundled
  the required `libzbar-64.dll`/`libiconv.dll` inside the wheel itself, so a
  plain `pip install pyzbar` *can* work standalone on Windows — but this is
  a known source of "ImportError: Unable to find zbar shared library" on
  some Windows/Python combinations depending on wheel availability for the
  exact interpreter ABI, and `aadhaar_qr.py` has no fallback if `pyzbar`
  fails to import (only OpenCV's `QRCodeDetector` is a fallback for
  *decoding*, aadhaar_qr.py:221-256, not for `pyzbar` failing to import — the
  `import pyzbar.pyzbar` at aadhaar_qr.py:127 is unguarded, so a DLL-load
  failure there raises before OpenCV is ever tried). I cannot confirm from
  source alone whether a `pyzbar==0.1.9` wheel exists for `cp312-win_amd64`
  specifically — that needs an actual `pip install` to verify, which was out
  of scope here.
- **`pytesseract` (ocr.py:445, 479)** is a thin subprocess wrapper — it does
  **not** bundle the Tesseract OCR engine. On Windows, Tesseract must be
  installed separately (e.g. the UB-Mannheim installer) and either placed on
  `PATH` or pointed to via `pytesseract.pytesseract.tesseract_cmd`, which
  this codebase never sets. Without it, `extract_text` degrades to
  `easyocr` — which is commented out of `requirements.txt`
  (requirements.txt:20) — and then to `engine="unavailable"`
  (ocr.py:455-470) with silent empty-text output, not a hard failure. So the
  app will *start* and *run* without Tesseract, but every OCR-dependent
  check (Aadhaar-number-from-OCR, PAN, marksheet subject matching) will
  produce empty/negative results with no error surfaced to the caller
  explaining why.
- **`mediapipe==0.10.20`, `deepface==0.0.93`, `tf-keras==2.18.0`**
  (face_match.py:83, 210) — these are the packages most likely to have
  Python-3.12/Windows wheel-availability constraints, and this is the one
  area I can least verify without actually running `pip install`. Two
  concrete, source-level observations rather than a version-support verdict:
  - `tf-keras` is a compatibility shim that itself depends on a matching
    `tensorflow` release, and **`tensorflow` is not listed anywhere in
    `requirements.txt`** — it would be pulled in transitively as `tf-keras`'s
    own dependency, which means the actual TensorFlow version installed is
    whatever `tf-keras==2.18.0` resolves to, not something this repo pins or
    controls directly.
  - `deepface.DeepFace.verify` (face_match.py:85-92) downloads model weights
    over the network on first use (this is `deepface`'s documented behaviour,
    not something visible in this repo's own code, since the download logic
    lives inside the `deepface` package) — so first-run behaviour at the
    venue depends on internet access being available, and nothing in this
    repo vendors or pre-fetches those weights.
  I did not find anything in this repo's own source that pins Python-version
  compatibility for these three packages, and confirming actual wheel
  availability for `cp312-win_amd64` requires either `pip install --dry-run`
  or checking PyPI directly, both out of scope for a source-only, no-install
  audit. **Flag this as the highest-uncertainty item in the whole audit and
  verify it explicitly before relying on this list.**

**Confirmed fine:** `fastapi`, `uvicorn[standard]`, `python-multipart`,
`cryptography`, `pillow`, `numpy`, `opencv-python-headless` are all
mainstream, well-maintained packages with routine Windows/3.12 wheel support,
and every symbol imported from them in this codebase (`fastapi.FastAPI`,
`cryptography.hazmat.*`, `PIL.Image`/`ImageChops`/`ImageEnhance`/`ImageOps`,
`numpy`, `cv2` headless API) is a standard, long-stable API surface.

---

## 4. Gaps vs. the team's plan

| Plan deliverable | Present in repo? | Evidence |
|---|---|---|
| Aadhaar QR verify | **Yes**, and it is the most complete module in the repo | `aadhaar_qr.py` (§2.4) |
| Verhoeff checksum | **Yes**, verified correct by execution | `verhoeff.py` (§2.1) |
| PAN format check | **Yes**, honestly scoped as format-only | `pan.py` |
| ELA tamper detection across all 3 doc types | **Yes** — `ela.analyse` is called from all three document endpoints (main.py:145, 320, 413) | `ela.py` |
| Marksheet layout/font consistency + field validation | **Partially present, partially absent.** Field *extraction* and range validation exist; the README explicitly says font-forensics was deliberately dropped ("I did **not** implement font-forensics from your plan", README.md:85-87) — that is a documented, deliberate cut, not a silent gap. What is *not* documented as cut, but is nonetheless absent, is the printed-total/percentage cross-check (§1, §2.9) — the code scaffolding for it exists (fields, reason codes, structural-problem set) but the comparison logic itself was never written. |
| Biometric face-match with liveness | **Yes**, both parts implemented and correctly scoped about their limits | `face_match.py` (§2.7) |
| Dashboard UI (Streamlit or React) showing flagged vs. verified docs with reasons and trends | **Entirely absent.** | No `.html`, `.jsx`, `.tsx`, `streamlit_app.py`, or any frontend file exists anywhere in the repository (confirmed by the same recursive listing used in §0 — the only files are the 13 backend files plus `.git/`). What exists is two JSON-returning backend endpoints, `GET /dashboard/history` and `GET /dashboard/summary` (main.py:552-559), which return the raw data a dashboard would need (verdict counts, per-day trend, top reason codes, per-check reason lists) but render nothing themselves. The CORS configuration hardcodes `http://localhost:3000` and `http://localhost:8501` as allowed origins (main.py:44) — i.e. the code anticipates a React (3000) or Streamlit (8501) frontend existing, but neither exists in this repo. **A frontend is 0% built.** |

---

## 5. Verdict

**KEEP CORE / EXTEND, with two specific fixes required before the backend is
demoable, and the dashboard UI built from scratch.**

This is not a "mostly fake" codebase — the two things a judge is most likely
to probe (Aadhaar signature cryptography and the face-match/liveness pairing)
are both real, non-trivial, correctly-scoped implementations, and I could
independently verify the Verhoeff module's correctness by running it
end-to-end. The README is unusually honest about what is and is not a real
verification (UNVERIFIABLE-for-PAN-and-marksheets, no invented accuracy
numbers, explicit statement of what liveness does not defeat) — that
intellectual honesty is worth preserving, not rewriting away.

But it is currently **not runnable at all**, for reasons that have nothing to
do with model/library maturity: the file layout doesn't match the imports
(§0), and a hard dependency is missing from `requirements.txt` (§2.6). Both
are mechanical, same-day fixes. Layered on top of that, one of the plan's
named deliverables — marksheet total/percentage cross-checking against the
*printed* total — has scaffolding but no logic (§1, §2.9), and the dashboard
UI is not started at all (§4).

**Concretely:**
- **Do not rewrite**: `verhoeff.py`, `aadhaar_qr.py`, `pan.py`, `verdict.py`,
  `store.py`, `face_match.py`, `ela.py`. These are working and reasonably
  well-scoped for a hackathon demo.
- **Fix, don't rewrite**: repository layout (§0 — move files into the
  `app`/`app.services` structure the code already assumes and add
  `__init__.py` files), `requirements.txt` (add `pymupdf`), `config.py:11`
  (add the missing type annotation so `uidai_cert_path` is a real,
  env-overridable field), source and commit a real UIDAI certificate (or a
  test fixture certificate plus a `tests/test_core.py` that the README
  already promises but that does not exist).
- **Finish, don't rewrite**: `marksheet.py` — add the printed-total/
  printed-percentage extraction and the `TOTAL_MISMATCH`/`TOTAL_CONSISTENT`/
  `PERCENTAGE_MISMATCH` comparison the scaffolding already anticipates.
- **Build from scratch**: the dashboard UI. Nothing to reuse here; the two
  JSON endpoints it would consume already exist and return sensibly-shaped
  data.

**Rough effort to a demoable state**, assuming the two people who wrote this
backend are available: half a day for the layout/dependency/config fixes and
sourcing a real cert (§0, §2.2, §2.4, §2.6); half a day to a day to finish the
marksheet total-check and add basic exception handling around the OCR/ELA/QR
calls in `main.py` (§2.6); one to two days for a minimal Streamlit dashboard
against the existing `/dashboard/*` endpoints (Streamlit is the faster path
given no frontend exists yet and the team's own CORS config already lists
port 8501); plus whatever time it takes to confirm the `mediapipe`/`deepface`/
`tf-keras` install actually succeeds on the target Windows/Python-3.12 demo
machine, which is the one item in this audit that genuinely cannot be
resolved by reading source and must be tested directly (§3). Call it 3-4
person-days total, most of it front-loaded into things that can be verified
within the first hour (run `pip install -r requirements.txt` on the actual
demo machine and see what breaks).
