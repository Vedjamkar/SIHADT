# PROJECT STATE — SiH_Verif

## Current implementation update — 2026-09-09

The older sections below preserve project history; their "no frontend" statements are superseded.
The React app now has a responsive examination workspace, an interactive synthetic scan,
an animated image-derived edge heatmap during upload/processing, visible backend forensic
map channels, guided camera capture for standalone and Aadhaar identity checks, and searchable history.
Preview animation is local image processing, not streamed backend progress. Deepfake/PAD
detection remains unavailable; blink/head-turn liveness does not cover those attacks.

Bug fixes include bounded and validated image/PDF/frame uploads, validated liveness challenges,
ordered open/closed/open blink detection, and `CHECK_FAILED` for inconclusive identity checks.
`BOUND` now requires both face match and liveness to succeed. API responses include actual
cosine distance; the frontend does not compare similarity against a distance threshold.
OCR/QR working image sizes are bounded. The HTTP client rejects malformed responses and
handles timeout/abort; camera cancellation and navigation release live streams.
Existing rounded audit scores are preserved; no audit-data migration was applied.

The frontend also includes an on-device document organizer. Imported files are stored as blobs
in browser IndexedDB, classified into editable identity, education, financial, medical, legal,
or other folders from their filenames, and can be searched, sorted, previewed, downloaded, or
removed. Organizer files are not sent to the verification API automatically, and live face
captures are never added to it. Successful verification submissions are stored automatically
with their document kind, latest verdict, identity-binding state, audit record ID, and any
related back-side file. A saved primary document can reopen its matching verification form with
the original front and back files already attached.

Validation commands: `npm run build` and `npm run lint` in `frontend/`;
`node --test tools/check_frontend_api.mjs`, `.venv/Scripts/python.exe -m unittest discover -s tests -v`,
and `.venv/Scripts/python.exe tools/check_frontend_ui.py` from the repository root.
Browser tests use synthetic images and a mock camera/API. Physical-camera and real-model
accuracy validation remain separate work. See `frontend/README.md` for startup instructions.

**Living handover document.** Anyone (human or AI agent) picking this up cold should read
this file first and be productive without asking anyone else. Update it whenever a decision
is made, a question is answered, or a module changes status.

- **Last updated:** 2026-09-08
- **Local working copy:** `D:\dev\SiH_Verif` (clone of `https://github.com/Prayag-Nair/SiH_Verif`)
- **Upstream:** https://github.com/Prayag-Nair/SiH_Verif
- **Plan document (source of truth for scope):** `D:\vedfr\Downloads\hackathon_project_plan.pdf`
  — extracted text mirrored in `docs/PLAN_EXTRACT.md`

---

## 1. What this project is

A document + identity verification app for Smart India Hackathon (SIH).

A user uploads a government or institutional document (Aadhaar, PAN, or marksheet). The app
returns a **verified / flagged verdict with explicit reasons**. A biometric face-match compares
a live selfie against the photo on the uploaded ID, to confirm the document belongs to the
person presenting it.

**Explicit non-goal, stated in the plan:** this is *not* a live government-database check.
It is a "does this look genuine" tool. The team must never claim official government
verification. This constraint drives the entire architecture — see §4.

### Hard constraints (from the plan document, non-negotiable)

| Constraint | Rule |
|---|---|
| Biometrics | Compare live, discard immediately. **Never store biometric data.** |
| Demo data | Only consenting teammates. Ask each person directly before using their ID or selfie. |
| Display | Blur real ID numbers on screen if a real document appears in the demo. |
| Claims | No claim of official government verification. |

---

## 2. Current repo state

FastAPI backend, flat module layout, no frontend.

| Module | File | Purpose |
|---|---|---|
| API surface | `main.py` | 5 verify endpoints + dashboard/history/summary/reasons/health |
| Aadhaar QR | `aadhaar_qr.py` | Secure QR decode + UIDAI RSA signature verification |
| Checksum | `verhoeff.py` | Verhoeff dihedral-group check digit on the Aadhaar number |
| PAN | `pan.py` | Structural/format validation |
| Marksheet | `marksheet.py` | Arithmetic consistency + range checks |
| Tamper | `ela.py` | JPEG Error Level Analysis |
| Biometrics | `face_match.py` | ArcFace embeddings + MediaPipe-landmark liveness |
| Verdict | `verdict.py` | Tiered verdict engine (cryptographic → structural → heuristic) |
| Storage | `store.py` | Verification history |
| Config | `config.py` | Consent env vars, thresholds, UIDAI cert path |
| OCR | `ocr.py` | Tesseract wrapper |

**Endpoints:** `/verify/aadhaar`, `/verify/aadhaar-full`, `/verify/pan`, `/verify/marksheet`,
`/verify/face`, `/dashboard/history`, `/dashboard/summary`, `/reasons`, `/health`

### Provenance — read this before judging the code

The repo has **3 commits, all titled "Add files via upload"** — every file was pushed through
GitHub's web UI, never from a working tree. Combined with the import defect below, the
conclusion is firm: **this code has never been executed.** It was AI-generated from the plan
document (module docstrings address the plan's author in the second person: *"Your plan says
demo data comes only from consenting teammates"*).

That is not the same as it being worthless. The code is unusually thoughtful for its origin —
the tri-state signature logic (§2.1), the server-side redaction, and the consent gate in
`config.py` are genuinely good decisions. But **nothing in it is verified**, one headline
feature is hollow (marksheet totals, below), and it must be treated as a detailed draft rather
than a working system.

### 2.1 The certificate question — resolved, and an earlier claim corrected

**Checked: there is no certificate anywhere in the repo.** No `certs/` directory, no `.cer`,
`.pem`, `.crt`, or `.der` file. Signature verification has therefore never run.

**Correction to an earlier assessment in this document:** this was initially called a
*fail-open* risk. That was wrong, and the code deserves credit. `aadhaar_qr.py:354-357` sets
`signature_verified = None` — a tri-state, explicitly *not* `False` and *not* `True` — and
emits `UIDAI_CERT_NOT_CONFIGURED`. `verdict.py:218` then falls through to
`Verdict.UNVERIFIABLE`. A missing certificate degrades to "cannot say", never to "genuine".
That is the correct and honest behaviour.

**The real consequence is a demo failure, not a security failure:** with no certificate loaded,
a *genuine* Aadhaar returns UNVERIFIABLE. Demo steps 1 and 2 in the plan both collapse. This
is still the highest-priority unblock, just for a different reason than first stated.

**Where to get the certificate:** UIDAI publishes the public certificate for Secure QR and
offline e-KYC signature validation on its
[certificate details page](https://uidai.gov.in/en/916-developer-section/data-and-downloads-section/19388-uidai-certificate-details-2.html)
(see also the [Secure QR Code Reader FAQ](https://uidai.gov.in/en/306-faqs/aadhaar-online-services/secure-qr-code-reader-beta.html)).

> **Critical distinction, and an easy way to lose a whole day:** the widely-circulated
> `https://uidai.gov.in/images/uidai_auth_stage.cer` is the **staging/test** certificate. It
> will **not** verify a real production Aadhaar card. Production cards are signed with the
> production key and need the production public certificate. If verification fails against a
> card everyone believes is genuine, check which certificate is loaded before assuming the
> code is broken.

### Audit status

- `docs/CODE_AUDIT.md` — **landed.** File-by-file audit. Summary in §2.2.
- `docs/ADVISORY.md` — **landed.** Threat model, forgery-defence analysis, legal position,
  ranked improvements. Its headline findings are summarised in §7.5.

### 2.2 Audit findings — confirmed by independent re-check

Each of these was verified directly, not taken on the audit's word.

| # | Finding | Evidence | Status |
|---|---|---|---|
| 1 | **The app could not start at all.** `main.py:30-33` used relative imports (`from .config`, `from .services import ...`) requiring a package layout that does not exist — flat repo, no `__init__.py`, no `services/`. | Read `main.py:30-33`; `ls -a` confirms flat layout | **FIXED** on branch `fix/runnable` |
| 2 | `pymupdf` imported unconditionally at `main.py:25`, absent from `requirements.txt`. Genuinely used at `main.py:371,385` to rasterise PDF uploads. | Grep confirms real usage | **FIXED** — pinned in requirements |
| 3 | `config.py:11` `uidai_cert_path` had **no type annotation**, so it was a plain class attribute, not a dataclass field — no env-var override, unlike every sibling setting. Precisely the setting you most need to point at a file. | Read `config.py:9-13` | **FIXED** — now `str` with `UIDAI_CERT_PATH` override |
| 4 | **`marksheet.py` has a dead headline feature.** `printed_total` / `printed_percentage` fields and the `TOTAL_MISMATCH` / `TOTAL_CONSISTENT` / `PERCENTAGE_MISMATCH` reason codes exist in the dataclass, the reason catalogue, and the structural-problem set — but nothing in `analyse()` ever assigns those fields or emits those codes. | Per audit, file:line cited in `CODE_AUDIT.md` | **FIXED** — implemented and verified, see task N3 |
| 5 | `verhoeff.py` is correct — verified by *execution*, not reading: a valid 12-digit number passes, the same number with one digit changed fails. | Audit ran it standalone | Verified good |
| 6 | `face_match.py` threshold direction is correct (distance ≤ threshold → match, for a cosine *distance* metric). | Audit checked; suspected inversion did not exist | Verified good |
| 7 | No frontend of any kind. Zero `.html` / `.jsx` / Streamlit files. Two JSON endpoints only. | `ls`, audit sweep | **OPEN — Ved's slot** |

**Finding 4 is the one that matters most for the demo.** The plan's demo script and the README
both lean on marksheet arithmetic as the "show it catching a fake, live" moment. That check
does not exist. It is also cheap to implement — parsing printed totals and comparing against
summed subject marks is an afternoon's work, and it is the *only* marksheet signal that is
deterministic rather than heuristic.

**Audit's overall verdict: KEEP CORE / EXTEND**, ~3–4 person-days to demoable. Concurred —
the cryptographic and biometric modules are real and well-scoped; the blockers were mechanical.

---

## 3. Gap vs the plan

The plan's task split assigns a **frontend + dashboard** (Streamlit or React) showing flagged
vs verified history, per-flag reasons, and trends. **No frontend exists in the repo.** Backend
dashboard *data* endpoints exist; there is no UI consuming them.

The plan also lists marksheet **layout/font consistency** checks. The repo's marksheet module
appears to do arithmetic/range validation only.

**Priority order if time runs short (from the plan, verbatim):**
QR verification > Verhoeff checksum > ELA tamper detection > face-match > dashboard polish.

---

## 4. The core technical argument (read this before touching code)

This is the reasoning the team must be able to defend to judges. It is also the correct
architecture, not just talking points.

### 4.1 Hashing (MD5 or otherwise) does not verify an unknown document

A hash proves **integrity against a known-good reference** — "is this byte-identical to the
copy I already trust?" For a document the system has never seen before, there is no reference
hash to compare against, so a hash proves nothing about authenticity. This holds for SHA-256
just as much as MD5. (MD5 is separately broken — practical collisions since 2004 — and must
not be used for any security decision regardless.)

**Where hashing legitimately belongs:** audit-log integrity, deduplication (has this exact
file been submitted before?), and chain-of-custody on the stored artifact. Those are real,
worth having, and cheap. They are not verification.

### 4.2 The three input paths, and what survives each

| Input | Cryptographic anchor available? | Correct primary check |
|---|---|---|
| Digitally-signed PDF (e-Aadhaar, DigiLocker-issued marksheet) | **Yes** — embedded PKCS#7 / PAdES signature | Validate the signature + certificate chain to the CCA India root |
| Photo/scan of a printed Aadhaar | **Yes** — the Secure QR carries a UIDAI-signed payload that survives printing | Decode QR, verify UIDAI RSA signature over the payload |
| Photo/scan of a printed PAN card or non-DigiLocker marksheet | **No** | Heuristics only — and the ceiling on what can be claimed is correspondingly low. Say so. |

The key insight for the printed-paper case: **a digital signature does not survive being
printed — but a QR code does.** The Aadhaar Secure QR is precisely a signed payload rendered
as ink, which is why it is the showpiece. Anything without such an anchor falls back to
heuristics, and heuristics cannot establish authenticity — only raise suspicion.

### 4.3 ELA is the weakest link and must not be overclaimed

Error Level Analysis detects JPEG recompression inconsistency. Two problems:

1. **It only works on JPEGs that retain their editing history.** Print a document and
   photograph it and the entire compression history is overwritten by the camera's single
   fresh encode. ELA on a print-scan cycle is close to meaningless — which is exactly the
   input path the plan centres on.
2. **The forensics community does not regard it as sound.** Image forensics expert Jens Kriese
   has called it *"subjective and not based entirely on science"* and *"a method used by
   hobbyists."* High-frequency content — sharp edges, fine texture, text — lights up brightly
   in ELA on completely authentic images, generating false positives.

**Implication:** ELA may stay as a *supporting* heuristic signal that flags a region for human
attention. It must never on its own produce a verdict a user would read as "forged." If a
judge asks about accuracy and the answer rests on ELA, the team loses. See
`docs/ADVISORY.md` for the assessment of whether the current code respects this line.

### 4.4 The replay attack is the question the team will be asked

Judges will ask: *"Can't a forger just copy a real Aadhaar QR code?"*

Yes — a forger can lift a genuine person's real Secure QR and print it on a card carrying a
**different photo and name**. The signature verifies perfectly. Signature verification alone
does not defeat this.

**The defence:** the Secure QR payload contains the holder's demographic fields *and an
embedded JPEG2000 photo*. So the system must close the loop:

1. Verify the UIDAI signature over the payload (proves the payload is genuine UIDAI data).
2. Extract the photo from the *signed payload* and compare it to the photo *printed on the
   card* — mismatch means the QR was transplanted.
3. Cross-check OCR'd name / DOB / gender on the card against the *signed* fields — mismatch
   means the printed text was altered.
4. Match the live selfie against the photo from the **signed payload**, not the printed photo
   — the signed one cannot be swapped.

That chain is the strongest thing this project can demonstrate, and it is a complete,
confident answer to the hardest judge question. Whether the current code implements steps 2–4
is the single highest-value open item.

### 4.5 Verdict honesty

The README describes "five verdicts, none saying 'verified'". This instinct is correct and
should be defended: the system distinguishes *cryptographically proven genuine* from
*structurally plausible* from *no forgery detected* — and the last of those is not a
statement about the document, it is a statement about the system's own limits. Any code path
that lets a heuristic-tier signal produce a strong-sounding verdict is a bug, not a feature.

---

## 5. Prior art — do not reinvent these

| Need | Use this | Notes |
|---|---|---|
| Aadhaar Secure QR decode, offline eKYC XML parse, embedded photo extraction | [`pyaadhaar`](https://github.com/tanmoysrt/pyaadhaar) (MIT, on PyPI) | Handles old QR, new Secure QR, and offline eKYC XML; extracts the user photo. Directly overlaps `aadhaar_qr.py`. |
| Same, alternative API | [`aadhaar-py`](https://snyk.io/advisor/python/aadhaar-py) | Secure-QR extraction only. |
| Signed-PDF (PAdES/PKCS#7) validation | [`pyHanko`](https://docs.pyhanko.eu/en/latest/cli-guide/validation.html) + `pyhanko-certvalidator` | The standard Python answer. Validates byte ranges, digests, and chains. **Gotcha:** India's CCA root is not in default trust stores — a genuine signature shows "not verified" until the CCA root is added. Worth knowing before the demo. |
| Reference offline QR reader UX | [AadhaarQRCodeReader](https://github.com/PtPrashantTripathi/AadhaarQRCodeReader) | Fully offline, no server — good privacy-story reference. |
| Issuer-side verified documents | DigiLocker APIs ([Decentro](https://decentro.tech/resources/digilocker-apis), [Surepass](https://surepass.io/digilocker-api/), [FRS Labs integration guide](https://www.frslabs.com/frsblog/2023/10/12/digilocker-how-to-integrate-digilocker-api-into-your-web-or-mobile-app-for-kyc/)) | Consent-based retrieval of *issuer-signed* documents. This is the real-world "how does this scale" answer for judges. Requires registration — likely out of scope for demo, but the team should be able to describe the path. |
| Tamper-detection benchmarks (for a real accuracy number) | DocTamper (170k document images), MIDV-2020 (1000 dummy ID docs, scans + photos + video), FantasyID | Lets the team answer "what's your accuracy, tested on what data?" with something other than a shrug. MIDV uses *dummy* documents — no consent problem. |
| Survey of the whole attack/detection space | [Identity Document Attack and Detection survey (arXiv)](https://arxiv.org/pdf/2607.01442) | Orientation reading. |

---

## 6. Scope decisions and remaining questions

### Answered — scope is locked

**Stage: internal college selection round.** Not a national SIH problem statement. Scope is
exactly as written in the plan document: Aadhaar / PAN / marksheet verification plus face-match.
No PS-specific reframing needed. (SIH25029 "Authenticity Validator for Academia" was considered
and ruled out as not applicable at this stage — noted in case the team advances and the PS
becomes academic-credential-focused, in which case §4 still holds but the marksheet path
becomes the showpiece.)

**Timeline: short — plan as days-to-two-weeks.** Everything below is ordered so work can stop
at any point and still leave a coherent demo. No task should be started that cannot be finished
and shown.

**Ved's role: cross-cutting — frontend, documentation, backend fixes. Effectively project
manager; no formal slot assigned.** Practical consequence: he owns the parts nobody else owns
and the parts that make the whole thing hang together — the dashboard/UI (unbuilt), this
document and the pitch material, and repairs to backend modules the audits flag. He is also
the person who must ensure the system does not overclaim, because that is a whole-project
property no single module owner will catch.

### Still open

1. Has anyone obtained the UIDAI certificate, and has QR verification been run end-to-end on a
   real card even once? (Fail-open risk, §2 — this is the demo's single point of failure.)
2. Consent: has each teammate whose ID/selfie will be used been asked directly, as the plan
   requires? This is a hard constraint, not a formality.
3. Is there at least one genuine Aadhaar available for the demo, and one deliberately-edited
   copy of it? Demo steps 1 and 2 in the plan both depend on this.

---

## 7. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-08 | Work in `D:\dev\SiH_Verif`, clone of upstream | Session scratch workspace is ephemeral; needs a durable home |
| 2026-09-08 | Split review into two passes: advisory/threat model, then mechanical code audit | Separates "is the approach right" from "is this code worth keeping" so neither biases the other |
| 2026-09-08 | MD5-based file verification rejected as a primary mechanism | §4.1 — a hash needs a trusted reference; none exists for an unseen document |
| 2026-09-08 | Scope locked to the plan document as written (internal college round, not a national SIH PS) | Confirmed with Ved |
| 2026-09-08 | Plan for a days-to-two-weeks budget; every workstream ordered to be stoppable at any point | Confirmed with Ved |
| 2026-09-08 | Ved owns frontend + docs + backend repair, cross-cutting rather than a single module | Confirmed with Ved; the dashboard slot was unclaimed and unbuilt |
| 2026-09-08 | **Do not pursue the UIDAI production certificate.** Run our own mock CA instead | Ved's call — procurement effort is disproportionate for an internal round, and real cards drag in consent and privacy problems. The verification code path is identical either way, so nothing technical is lost. See §2.1 |
| 2026-09-08 | **Demo faces must be synthetic** — AI-generated or public-domain portraits, downloading permitted. Never a real identifiable person, never a teammate's actual ID | Ved's call. Removes the consent problem entirely and lets the face-comparison path genuinely execute |
| 2026-09-08 | **`enforce_detection=False` is rejected** as a way to make the mock's silhouettes compare | Ved's call. Embeddings of non-faces are meaningless; it would make the demo appear to work when it does not. Honesty over a green tick |
| 2026-09-08 | **Nothing is pushed to the remote and no PR is opened.** All work stays on local branch `fix/runnable` | Ved's call. Repo is shared with teammates; he reviews before the team sees any of this |
| 2026-09-19 | **Model weights stay out of git; fetched by script into `models/`** | Two files exceed GitHub's 100 MB cap and Git LFS quota is not worth spending on a hackathon repo. A pinned manifest plus `tools/fetch_models.py` gives a fresh clone the same bytes, verified by hash |

---

## 7.5 Advisory findings — verified

Full analysis in `docs/ADVISORY.md`. The two highest-stakes findings were re-verified by
reading the code directly; both confirmed exactly as reported.

### A. The QR-replay hole is OPEN — and the README claims it is closed

**This is the project's central defect.** `README.md:150-154` states that `/verify/aadhaar-full`
compares the live face against the photo *inside the signed QR payload*. It does not.

`main.py:227-230` — on the documented two-sided path (`back_document` supplied):

```python
if back_bytes is not None:
    # New cards: the printed photograph is on the FRONT, while the QR is
    # on the BACK. Compare the live face with the FRONT card image.
    face_source = front_bytes
```

The signed photo is decoded (`aadhaar_qr.py:411`) and reported as available (`main.py:168`),
then **never used** on this path. It is consulted only on the legacy one-sided branch
(`main.py:231-233`).

**The attack, start to finish:** forger prints their *own* photo on the front and a *stranger's
genuine* Secure QR on the back. Signature verifies against real UIDAI data → `GENUINE_SIGNED`.
Live selfie matches the forger's own printed photo → `BOUND`. **Clean pass on a forgery.**

Compounding it, `verdict.py:206-218` is an `elif` chain: `crypto_pass` returns
`GENUINE_SIGNED` *before* `structural_fail` is examined. A printed Aadhaar number failing
Verhoeff — the exact fingerprint of a transplanted QR — is demoted to advisory under the
banner "Issuer-signed and unaltered."

The reasoning slip is visible in the code comment at `verdict.py:209-211`: *"the signature
covers these exact bytes."* True of the QR payload bytes. **False of the printed card**, which
is unsigned and entirely attacker-controlled.

There is also **no OCR-vs-QR cross-check anywhere** — not name, DOB, nor gender — despite
`main.py:138-143` already holding both values needed for a free `reference_id[0:4]` vs OCR'd
last-4 comparison.

**The fix (this is the single highest-value change in the project):**
1. `face_source` must prefer `qr_result.photo_jp2` whenever it exists — match the selfie
   against the *signed* photo, never the printed one.
2. Additionally compare the printed front photo against the signed photo. Mismatch =
   transplanted QR = the strongest possible forgery signal.
3. Cross-check OCR'd name / DOB / gender against the signed fields.
4. Fix the `elif` chain so a structural failure is never masked by a valid signature.

This also converts the hardest judge question — *"can't a forger just copy a real QR?"* — from
a loss into the demo's strongest moment.

### B. ELA fires on almost everything — the system makes false accusations

`ela.py` uses `FLAG_SIGMA=2.5` with `MIN_FLAGGED_FRACTION=0.004`. The firing threshold sits
*below* the ~0.62% null exceedance rate for that sigma, so `ELA_LOCALISED_ANOMALY` fires on
nearly every JPEG. `verdict.py:215-216` then lets that flag alone drive `NEEDS_REVIEW` —
directly contradicting `verdict.py:25`'s own stated rule that ELA is "never the sole cause of
a flag."

`ela.py:65` also gates on container format only, so a phone photo of a printed document
reports `applicable=True` — precisely the case where ELA is categorically meaningless (single
compression history, no region differential). See §4.3.

**Fix:** raise the threshold above the null rate, honour the never-sole-cause rule in code, and
set `applicable=False` when the image shows a single compression history.

### C. Other confirmed issues

| Issue | Location | Why it matters |
|---|---|---|
| Certificate is never pinned — `load_*_certificate` discards the cert after extracting the key | `aadhaar_qr.py:481-489` | A self-signed cert dropped in `certs/` validates **every** forgery. Pin the expected fingerprint — a legitimate use of hashing (§4.1). |
| `redacted()` masks 4 chars of `reference_id` but returns full **name, DOB, and address** | `aadhaar_qr.py:92-100` → `main.py:167` | Violates the plan's own redaction constraint. Bad look if a judge notices. |
| No PDF signature handling at all; `/verify/aadhaar` and `/verify/pan` **HTTP 500** on an e-Aadhaar PDF | — | Judges may well upload their own e-Aadhaar PDF. A crash is worse than a refusal. |
| Failed face-match reports as `NOT_ATTEMPTED` | `verdict.py:_binding` | A non-match must read as a non-match. |
| Raw exception strings enter the audit DB as reason codes | `store.py` path | Leaks internals into the UI. |
| `tests/test_core.py` referenced in README, does not exist | — | Nothing is tested. |

Advisory also delivers a judge-ready legal paragraph (§57 / Puttaswamy 2018 / 2019 amendment /
offline-verification boundary / DPDP 2023), with external legal facts marked **[VERIFY]**
rather than asserted. Read it before the pitch; do not quote it unchecked.

---

## 7.6 Strategy — scope ambition vs. what is provable

Ved's read of the team's real ambition: a **KYC / self-hosted-DigiLocker-style system**
attacking the weaknesses of existing ones — deepfake detection and "raw paper" verification.
That is a sharper and more interesting problem than the plan document states. Two honest
constraints on it:

**1. "Prove a raw printed paper legitimate by software" is not achievable — by anyone.**
Without a cryptographic anchor, software can *detect some forgeries* but can never *establish
authenticity*. Absence of detected tampering is a statement about the detector's limits, not
about the document. This is not a gap in the team's skill or effort; it is information-theoretic.
Any team claiming otherwise at a hackathon is overclaiming, and a sharp judge will find it.

The productive move is to **change the document, not the detector**: the way unanchored
documents become verifiable is issuer-side signing — the issuer signs the credential, the
verifier checks the signature. That is exactly what DigiLocker is, what the Aadhaar Secure QR
is, and what W3C Verifiable Credentials standardise. A demo that *shows* the difference — an
unanchored marksheet reaching only "no forgery detected", the same marksheet issuer-signed
reaching "cryptographically genuine" — makes the point better than any forensics score, and is
buildable in the time available.

**2. Deepfake / presentation-attack detection IS a real and tractable gap.** This is where the
"weakness of existing KYC" thesis genuinely holds. Current `face_match.py` liveness is a
MediaPipe-landmark blink check — defeated by a video replay on a phone screen. Passive
presentation-attack detection (moiré/screen-door artifacts, specular and texture analysis) is a
legitimate, defensible contribution and directly answers "how is this better than existing KYC."

**Recommended framing for the pitch:** *"Existing KYC verifies the credential but trusts the
camera. We verify the credential cryptographically, bind it to a live human, and are honest
about the documents where cryptography is unavailable."* That is defensible, accurate, and
distinguishing.

## 7.7 Language / stack decision

Ved's concern: an all-Python codebase is a narrow foundation for the team's ambition.

**Assessment: partly agreed, with a caution.** Polyglot is a cost, not a virtue in itself, and
judges award nothing for language count. With a days-to-two-weeks budget and a student team,
splitting across four languages ships less, not more. Each language must earn its place.

Where Python is correct and should not be replaced: CV/ML (ArcFace, MediaPipe, deepfake
detection), OCR, image forensics, and the cryptographic verification. There is no serious
alternative for the first three.

Where a second language genuinely earns its place **now**:
- **Frontend — TypeScript/React.** Non-negotiable, and already the unbuilt slot. This alone
  makes the codebase polyglot in the way that matters. (Streamlit is the fast fallback if time
  collapses, at a real cost to demo optics.)

Where a third language earns its place **only if the issuer-signing route is taken and someone
already knows the language**:
- An **issuer-side signing / credential-registry service** — Go or TypeScript both reasonable.
  Key management, signing endpoints, a registry. This is the "own DigiLocker" component.

**Recommendation:** build Python backend + TypeScript/React frontend now. Design the
service boundary so a signing service *could* be a separate process in another language, and
present that architecture. Judges reward a credible scaling story; they do not require it to be
built. **Open question for the team: what languages does everyone actually already know?**
That constrains this more than any architectural preference.

---

## 8. Next actions

Ordered so work can stop at any point and still leave a coherent demo. Do not start anything
lower down while something above it is open.

Ordered so work can stop at any point and still leave a coherent demo. Do not start anything
lower while something above it is open.

### DONE and verified by execution (branch `fix/runnable`)

- [x] Scope locked (§6); both audits landed
- [x] **Repo made importable.** It had never run. Flat imports, `pymupdf` pinned,
      `uidai_cert_path` made a real env-overridable field.
- [x] **App boots.** `/health`, `/reasons`, `/dashboard/summary` all return 200.
- [x] **Mock certificate authority** (`tools/mock_pki.py`) — replaces the UIDAI cert entirely.
      Decision: we do NOT chase the production certificate. See §2.1.
- [x] **`int()` limit fix** — Python 3.11+ caps int↔str at 4300 digits; a real Secure QR
      payload exceeds it, so `int(payload)` would have raised on a genuine card at demo time.
- [x] **QR-replay hole CLOSED.** Selfie now matches the signed photo; added printed-vs-signed
      photo comparison and printed-vs-signed field cross-check; new `SIGNED_BUT_ALTERED` verdict.
- [x] **`elif` chain fixed** — structural failures are no longer masked by a valid signature.
- [x] **"ELA never the sole cause" now enforced in code**, not just stated in a comment.
- [x] **Frame-count validation reordered** — it sat after the code that indexed the list.
- [x] **Face stack resolved on Windows + Python 3.12** — mediapipe 1.0.1, deepface 0.0.100,
      TensorFlow 2.21.0 install and import cleanly. This was the audit's last open unknown.
- [x] **Model files made reproducible (2026-09-19)** — the ~800 MB of pretrained weights
      (ArcFace, RetinaFace, DeepFace age model, MediaPipe Face Landmarker) were only ever in
      one developer's `~/.deepface/weights`, so a fresh clone had no face pipeline. Now
      `face_match.REQUIRED_MODELS` pins URL + SHA-256 + size for each, `tools/fetch_models.py`
      downloads them atomically into the gitignored `models/` (`config.py` sets
      `DEEPFACE_HOME` there), the launcher runs it, `/health` reports `face_models_ready`,
      and a missing file fails fast with the command to run instead of downloading inside a
      request. Also fixed in passing: liveness was crashing with
      `module 'mediapipe' has no attribute 'solutions'` — mediapipe 1.x removed the legacy
      Face Mesh API; `_landmarks` now uses the Tasks `FaceLandmarker` (same 478-point
      topology, so the EAR/yaw indices are unchanged). Verified end to end on the synthetic
      pair: same-face match, different-face no-match, age estimate, blink/head-turn checks.

Verdict behaviour, confirmed by running `assess()`:

| Input | Verdict |
|---|---|
| Valid signature, clean | `GENUINE_SIGNED` |
| Signature broken | `FORGED_SIGNATURE` |
| Valid signature + photo mismatch | `SIGNED_BUT_ALTERED` |
| Valid signature + number mismatch | `SIGNED_BUT_ALTERED` |
| Valid signature + failed checksum | `STRUCTURALLY_INVALID` |
| One ELA flag alone | `UNVERIFIABLE` (flag demoted to advisory) |
| Two heuristic flags | `NEEDS_REVIEW` |

### NEXT — in this exact order

**N1. DONE — the replay catch is demonstrated, not merely asserted.**

Verified end to end through the real pipeline, with the mock CA certificate loaded:

| Specimen | Signature | Signed photo vs printed photo | Verdict |
|---|---|---|---|
| `genuine` | valid | match, distance 0.0654 | `GENUINE_SIGNED` |
| `replay` | **valid** — the QR genuinely is signed | **mismatch, distance 0.7024** | **`SIGNED_BUT_ALTERED`** |

The earlier open question is answered: a face **is** still detectable after compression to
96×96 greyscale at ~1400 bytes for the QR budget. The first `NOT COMPARED` result was DeepFace
downloading its weights, not a detection failure.
(That failure mode no longer exists: `compare_faces` now refuses to run without the model
files present and says so, rather than downloading mid-call — run `tools/fetch_models.py`.)

Reproduce with:

```bash
./.venv/Scripts/python.exe tools/mock_pki.py card   --photo demo_data/faces/victim.jpg
./.venv/Scripts/python.exe tools/mock_pki.py replay --photo demo_data/faces/victim.jpg --attacker-photo demo_data/faces/attacker.jpg
./.venv/Scripts/python.exe tools/check_face_pipeline.py
```

> **Margin worth watching before the demo.** The two synthetic faces separate at distance
> 0.6889 against a 0.68 threshold in the isolated check, and 0.7024 through the full pipeline.
> That is a thin margin. A different pair of faces could fall the wrong side and produce a false
> match — which on the replay specimen would mean the attack passes. **Try several face pairs
> before relying on this in front of judges**; if the margins stay this tight, the 0.68 threshold
> deserves review rather than trust. Note the threshold is DeepFace's tuned default for ArcFace,
> so changing it is a considered decision, not a free knob.

**N1-original (for reference).** The photo-comparison branch was written but had never executed.

Progress so far:

- Two synthetic faces (AI-generated, nobody real) downloaded to `demo_data/faces/victim.jpg`
  and `attacker.jpg`, 1024×1024. `demo_data/` is gitignored, so they are not in the repo —
  re-download if missing, from `https://thispersondoesnotexist.com/random-person.jpeg`
  (the bare domain now returns an HTML wrapper, not the image; a browser User-Agent is needed).
- They compress through `mock_pki._encode_photo()` to 96×96 at ~1400 bytes, inside the
  1800-byte QR budget. So size is **not** the blocker.
- `tools/check_face_pipeline.py` exists to answer the open question. Run it directly —
  do **not** pipe it through `grep`/`tail`, which masks its exit code.

**Open question, deliberately not answered yet:** a first run returned `NOT COMPARED`, but
DeepFace was still downloading its weights at the time (`arcface_weights.h5` was a partial file
in `~/.deepface/weights/`, and RetinaFace had not started). So it is **not yet known** whether
a face is detectable at 96×96 greyscale, or whether that run simply failed on absent weights.
Let the weights finish downloading — roughly 260 MB total on a ~450 kB/s link — then re-run.

If the comparison then works, N1 is done: wire the faces into the mock via `--photo` /
`--attacker-photo` and confirm the `replay` specimen yields `SIGNED_BUT_ALTERED` through
`QR_PHOTO_MISMATCH_PRINTED`. If a face genuinely cannot be detected at that size, raise
`PHOTO_BUDGET_BYTES` and loosen the compression ladder in `mock_pki.py`; if the payload then
exceeds QR capacity, **say so plainly** — that is a real constraint worth reporting, not
something to paper over. Do not set `enforce_detection=False` to force a pass (decision log).

**N2. DONE.** `requirements.txt` corrected to the versions verified working on Windows +
Python 3.12, plus `qrcode[pil]` and `httpx2` which were used but never declared.

**N3. DONE — the marksheet total check now exists and is verified.**
`_extract_printed_total()` and `_extract_printed_percentage()` added to `marksheet.py`, compared
against the totals computed from the subject rows. Verified on CBSE-format input:

| Input | Result |
|---|---|
| genuine, computed 457 = printed 457 | `TOTAL_CONSISTENT` → `UNVERIFIABLE` |
| forged, computed 457 vs printed 487 | `TOTAL_MISMATCH` + `PERCENTAGE_MISMATCH` → `STRUCTURALLY_INVALID` |

Note the genuine sheet reaching only `UNVERIFIABLE` is correct, not a bug — a marksheet has no
cryptographic anchor, so "no forgery detected" is the honest ceiling. This pairing is a good
thing to show a judge: it demonstrates the verdict ladder refusing to overclaim on a document it
genuinely cannot prove.

*Known pre-existing limitation:* `_extract_subject_marks` assumes the CBSE layout where a row's
last three numbers are theory, internal and obtained total. A marksheet printing an explicit
"maximum marks" column will have that maximum read as the obtained mark. Worth handling if the
demo uses a non-CBSE sheet.

**N4. PARTIALLY DONE — needs validation against a real photograph.**
Thresholds corrected: at 2.5 sigma the null rate is ~0.62% of blocks, and the old firing point
was 0.4% — *below* chance, so ELA flagged nearly every image. Now 3.0 sigma firing at 2%.
Also added `_looks_like_camera_capture()`, so a JPEG straight from a camera reports
`applicable=False` with `ELA_NOT_APPLICABLE_CAMERA_CAPTURE` instead of pretending to analyse a
single-compression image.

**Still open and important:** the new thresholds are justified arithmetically but were NOT
demonstrated to still catch a real splice. Synthetic noise images do not exercise ELA — uniform
noise produces near-identical block means, so nothing is an outlier at either the old or new
setting, and all test cases returned 0.0000. **Validating this requires a real photograph of a
real printed document with a real edit.** Until someone does that, do not claim ELA works.

**N5. DONE.** `redacted()` now masks name, DOB and every address field to a first character plus
asterisks, alongside `reference_id`. State and pincode stay — too coarse to identify anyone, and
they keep the demo legible as a real record. Verified: `'Asha Devi'` → `'A********'`.

**N11. DONE (ahead of order).** README reconciled with reality — it had become misleading in the
*opposite* direction, marking as `[BROKEN]` several things now fixed and verified. Also fixed a
dead link to a `docs/SHIP_PLAN.md` that was never written, and the verdict list that said five
when there are now six.

**TESTS. DONE — `tests/test_core.py` now exists.** The original README told the team to run this
file before demo day; it had never existed. 17 tests, 0.19s, stdlib `unittest` only:

```bash
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

It pins Verhoeff's two defining properties exhaustively, every rung of the verdict ladder
(including that a transplanted QR outranks a valid signature), the marksheet check in both
directions plus the missing-total case that must not become an accusation, and the ELA
threshold-vs-null-rate arithmetic that was inverted for the project's whole life. Face matching
is excluded deliberately — ~260 MB of weights would make it a suite nobody runs;
`tools/check_face_pipeline.py` covers that separately.

**PARTIAL — raw exception text no longer leaks into reason codes.** Both `face_match` error
handlers pushed `str(exc)` or the exception class name into `reasons`, which flows into the
audit database and out to a UI with no `REASON_TEXT` entry to translate it. Diagnostics now go
to a new `detail` field. `store.py` may still have similar paths — not yet audited.

**N6. DONE.** Certificate pinning implemented. `certificate_fingerprint()` hashes the DER
encoding; `load_uidai_public_key(path, expected_fingerprint=...)` refuses to load on mismatch,
returning `None` so the system degrades to `UNVERIFIABLE` rather than trusting the wrong key.
Set `UIDAI_CERT_FINGERPRINT`; `mock_pki.py init` now prints the value. `/health` reports
`uidai_certificate_fingerprint` and `uidai_certificate_pinned`.

Tested against the real attack: a validly-formed rogue self-signed certificate **loads when
unpinned** and **is refused when pinned**. Mock CA fingerprint is
`527aecd5eab5a18b5d4d787052d5ccea63c3b4cb5edbaa87a9aa5926f87ea30e`.

**N9. DONE.** PDF uploads no longer return HTTP 500 on the Aadhaar and PAN endpoints.
`rasterise_if_pdf()` applies at every upload site and detects PDFs by `%PDF-` magic bytes
rather than the client-supplied `content_type`. Verified through the HTTP API:

| Upload | Result |
|---|---|
| genuine QR (PNG) | 200 → `GENUINE_SIGNED` |
| tampered QR (PNG) | 200 → `FORGED_SIGNATURE` |
| genuine QR wrapped in a PDF | 200 → `GENUINE_SIGNED` *(previously 500)* |
| corrupt PDF | 400 with a message *(previously 500)* |

**BACKEND GATE PASSED.** 22 tests green, and the API verified operational on mock data end to
end. This was the precondition for starting frontend work.

**N7. Failed face-match must report as failed**, not `NOT_ATTEMPTED` (`verdict.py:_binding`).

**N8. Deepfake / presentation-attack detection.** Currently absent — liveness is a MediaPipe
blink check, defeated by a video on a phone screen. This is the project's genuine differentiator
(§7.6) and the honest answer to "how is this better than existing KYC". Scope carefully: passive
screen-replay detection (moiré, specular, texture) is achievable; a general deepfake detector is
not, in this timeframe.

**N9. PDF uploads** — `/verify/aadhaar` and `/verify/pan` return HTTP 500 on an e-Aadhaar PDF.
A judge may well upload one. A clear refusal beats a crash.

**LINT SWEEP. DONE.** A dedicated agent ran `ruff`, `compileall`, the test suite and an AST
scan. Results worth recording:

- **Clean:** every reason code emitted anywhere has a `REASON_TEXT` entry (AST-verified across
  all emitter modules); no use-before-assignment on any endpoint path; no dataclass
  field/construction mismatches; no mutable default arguments, bare `except:`, or `== None`.
- **One real defect, fixed:** `aadhaar_qr` appended the raw exception message as a second entry
  in `reasons`, which is contractually a list of translatable codes — the same defect class
  already fixed in `face_match`. It reached the audit database and the UI as an untranslatable
  pseudo-code carrying internal error text. Detail now goes to a `detail` field.
- **Dead code removed**, each verified harmless first: an unused `ImageFilter` import (QR
  decoding re-tested on all three specimens afterwards, since no test covers that path),
  discarded `contact_hashes`, an unread block count in `ela`, an unused local in `ocr`, and a
  discarded `ok` in `main`.
- **Known and accepted:** ~15 silent `except` blocks in best-effort fallback loops (multiple QR
  decoders, OCR engines, certificate encodings). They convert failure into a proper reason code
  or `None`, so nothing is hidden from the verdict — but none log, so a genuine environment
  problem (pyzbar missing, tesseract absent) is indistinguishable from "nothing found" in the
  logs. **Worth adding `logger.debug` to each; not yet done.**

**N10. Frontend — IN PROGRESS.** Two agents running in parallel on separate file trees so they
cannot collide:

- **Structure/data-flow agent** owns `frontend/` — Vite + React + TypeScript, the API client,
  views (upload, result, dashboard), and all state handling. Told to define semantic class names
  and stable `data-anim` hooks, and to write only placeholder CSS.
- **Design/motion agent** owns `frontend/src/styles/` and `frontend/src/motion/` — design
  tokens, light and dark themes, component CSS against those class names, and a GSAP module
  keyed to the `data-anim` hooks.

Both were given the product rules that are not negotiable: never render "verified" or a bare
green tick; keep `verdict` and `identity_binding` on separate axes; `UNVERIFIABLE` must look
neutral rather than like a failure; always show the disclaimer and plain-language reasons; and
design for the false positive, because most flagged documents belong to honest people with poor
scans, not criminals.

`gsap` is not installed yet — integration step for the main session.

**N11. Reconcile the README** with whatever is true when the above lands.

### Decisions still open

- [ ] Keep `aadhaar_qr.py` or swap to [`pyaadhaar`](https://github.com/tanmoysrt/pyaadhaar)?
      Leaning keep — it is well-written, and the replay fix is now in it.
- [ ] What languages does the team actually know? (§7.7)
- [ ] Issuer-side signing / ledger demo (§7.6) — high pitch value, needs a time budget call.
      A ledger earns its place for issuance and revocation, not for verifying arbitrary uploads.
