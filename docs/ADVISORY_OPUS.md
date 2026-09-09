# Threat-model and architecture advisory — SiH_Verif

Reviewed: `main.py`, `aadhaar_qr.py`, `verhoeff.py`, `pan.py`, `marksheet.py`, `ela.py`,
`face_match.py`, `ocr.py`, `verdict.py`, `store.py`, `config.py`, `README.md`,
`requirements.txt` at commit `bb81087`.

This is an advisory document. No source file was modified.

Claims about repository behaviour carry `file:line` references. External facts I could not
verify from the repository are marked **[VERIFY]** — do not state those to a judge without
checking them yourselves first.

---

## 0. Executive summary — the five things that matter

Ranked by how much damage each does if a judge finds it before you admit it.

1. **The QR-replay hole is open, and the README claims it is closed.**
   `README.md:150-154` says `/verify/aadhaar-full` "compares the live face against the photo
   *inside the signed QR payload* rather than a crop off the card face." On the documented
   two-sided path this is false: `main.py:221-223` sets `face_source = front_bytes`, the
   printed card image. The signed photo (`qr_result.photo_jp2`) is used only on the legacy
   single-image branch (`main.py:225-227`). The strongest sentence in your pitch is
   contradicted by the code it describes. Fix this first.

2. **A valid signature masks every structural failure.** `verdict.py:210-212` returns
   `GENUINE_SIGNED` on `crypto_pass` without ever evaluating `structural_fail`. A card whose
   printed Aadhaar number fails Verhoeff, but which carries a genuine transplanted QR, is
   reported "Issuer-signed and unaltered" with the Verhoeff failure demoted to *advisory*.
   The tiering rationale is right for ELA noise and wrong here: **the UIDAI signature covers
   the QR payload bytes only. It says nothing about the rest of the card.** The code
   conflates "the payload is genuine" with "the document is genuine".

3. **The marksheet demo moment does not exist.** `README.md:82-85` names "subject marks that
   do not sum to the printed total" as the thing to show a judge live. `TOTAL_MISMATCH` and
   `PERCENTAGE_MISMATCH` are declared (`marksheet.py:39-40`), textualised
   (`verdict.py:94,96`) and tiered as fatal (`verdict.py:141-142`) — but **never emitted**.
   `printed_total` and `printed_percentage` are never populated (`marksheet.py:62-64`); the
   code never reads them off the sheet, so it cannot compare them.

4. **There is no PDF signature path at all**, and an e-Aadhaar PDF — the single most common
   artefact a real user actually has — causes an HTTP 500 on `/verify/aadhaar` and
   `/verify/pan`. This is simultaneously your biggest missing crypto win and a live demo
   crash.

5. **The repository as committed does not run.** `main.py:30-31` imports
   `from .config import settings` and `from .services import aadhaar_qr, ...`; there is no
   `app/` package and no `services/` subpackage — the files are flat at the repo root.
   `pymupdf` is imported at module scope (`main.py:25`) and is absent from
   `requirements.txt`. `README.md:26` points at `tests/test_core.py`, which does not exist.
   A judge who clones and runs gets an `ImportError`.

Everything below expands these and answers the seven questions asked.

---

## 1. MD5 and hashing: what a file hash can and cannot prove

### The short answer to your teammate

**No. Hashing is not a document-authenticity mechanism, and no hash function — not MD5,
not SHA-256, not SHA-3 — fixes that.** The weakness is not in MD5. It is in the threat
model.

### The precise argument

A cryptographic hash is a *comparison* primitive. `H(x)` on its own is meaningless. It only
becomes evidence when you compare it against a reference value `H(x_expected)` that you
obtained from a source you already trust, through a channel the attacker cannot influence.

Your system has no such reference. The stated problem is: *a user uploads a document the
system has never seen before, from an issuer whose database you explicitly do not query.*
So:

- You compute `H(uploaded_file)`.
- You have nothing to compare it to.
- Therefore the computation carries zero bits of information about authenticity.

This holds for a forged document and a genuine one identically: both hash to *something*,
and both hashes verify against themselves. An attacker who edits a scan simply produces a
different, equally self-consistent hash. There is no "hash of a genuine Aadhaar" to check
against, because Aadhaar cards are not published artefacts — each is unique per person and
per print, and UIDAI does not publish per-document digests.

Contrast with the case where hashing *does* work: you download `ubuntu.iso`, and the
publisher independently posts `SHA256SUMS` on a site you trust over TLS. Two channels, one
trusted reference. Nothing in your architecture has that shape.

### On MD5 specifically

MD5 is broken for collision resistance — practical chosen-prefix collisions have been
demonstrated (Stevens et al.), meaning an attacker can construct two different files with
the same MD5. It is also broken in ways that matter for exactly this kind of use: colliding
PDF and JPEG pairs that render differently but hash identically are publicly available.
So if you ever did have a reference-hash architecture, MD5 would let an attacker swap the
document under the hash.

But say this second, not first. **"MD5 is weak, use SHA-256" is the wrong correction here,
because it implies the design would work with a stronger hash. It would not.** If a judge
asks and you answer only "MD5 is collision-prone", a sharp judge will follow with "so use
SHA-256 then?" and you will have talked yourself into defending a broken design.

### The mechanism your teammate is actually reaching for

Their instinct — "there should be a cryptographic proof attached to the file" — is correct.
The mechanism that provides it is a **digital signature**, not a hash. A signature is
`Sign(H(x), issuer_private_key)`, and it works precisely because it binds the hash to an
*identity* whose public key you can obtain independently and pin. The hash is an internal
component of the signature; it is not the security property.

You already have exactly one instance of this done correctly: `aadhaar_qr.py:360-365`
verifies SHA256-with-RSA over the Secure QR payload. That is the right shape. Extend it
(Section 2), do not replace it with hashing.

### Where hashing legitimately belongs in this system

Three places. All are integrity/hygiene, none is authenticity.

| Use | What it buys you | Where it goes |
|---|---|---|
| **Audit-log chain of custody** | Prove your own audit record was not edited after the fact. Store `sha256(uploaded_bytes)` in `checks`, and chain each row: `row_hash = sha256(prev_row_hash ‖ row_fields)`. Then a tampered history is detectable. | New nullable columns on `store.py:24-36`. ~40 lines. |
| **Deduplication / abuse detection** | Detect the *same file* re-submitted many times, or one QR image submitted against many different selfies — which is a genuine replay-attack indicator. | `store.py`, plus a count query in `summary()`. |
| **Trust-anchor pinning** | Pin the SHA-256 fingerprint of the UIDAI signing certificate and publish it in your README, so "how do you know that .cer is UIDAI's?" has an answer. `README.md:471-473` already tells you to do this and `aadhaar_qr.py:466-489` does not — it loads the blob, extracts the public key, and discards the certificate entirely. | `aadhaar_qr.py:load_uidai_public_key` + `main.py:567-574`. ~30 min. |

The third is the highest-value 30 minutes in this document. Right now, if anyone drops a
self-generated certificate into `certs/`, every fabricated QR they sign verifies as
`GENUINE_SIGNED`, and `/health` (`main.py:571`) reports only `uidai_certificate_loaded:
true`. That is the entire cryptographic tier resting on an unauthenticated file path
(`config.py:11`).

**Privacy note on hashing uploads:** do not store `sha256` of a raw Aadhaar *number* as a
pseudonym. A 12-digit space is ~10^12 with a known leading-digit rule and a Verhoeff
constraint — roughly 9×10^10 valid candidates, which is trivially brute-forceable on a
laptop. A hash of a low-entropy identifier is not anonymisation. Hash the *file bytes*, not
the identifier.

### One-line answer for the judge

> "A hash proves a file hasn't changed since *we* saw it. It can't prove a document is
> genuine, because there's no trusted reference hash for a document nobody has seen before —
> and that's true of SHA-256 as much as MD5. What actually proves issuance is a digital
> signature, which is what we verify on the Aadhaar Secure QR. We use hashing for audit-log
> integrity and duplicate detection, which is what it's good for."

---

## 2. Digitally-signed PDFs — the correct mechanism, and what the repo does

### 2.1 Does the codebase handle signed PDFs?

**No. Not at all.** Confirmed by reading every file:

- The only PDF handling anywhere is `main.py:370-391`, in `/verify/marksheet`. It opens the
  PDF with PyMuPDF, rasterises **page 0 only** at 2× into a JPEG (`main.py:384-389`), and
  closes it (`main.py:391`). Any embedded PKCS#7 signature, the document catalog, the
  `/AcroForm` `/SigFlags`, and pages 2..n are discarded.
- `/verify/aadhaar` (`main.py:105`) and `/verify/pan` (`main.py:305`) have **no PDF branch
  at all**. Their bytes go to `aadhaar_qr.read_qr_payloads` → `Image.open`
  (`aadhaar_qr.py:129`) or `ocr._preprocess` → `Image.open` (`ocr.py:73`). PIL cannot decode
  PDF. Neither call site has a try/except (`aadhaar_qr.py:500` is unguarded), so this raises
  `UnidentifiedImageError` and returns **HTTP 500**.
- `grep` for `pkcs7|pades|byterange|digilocker` across the repo returns nothing.

So: upload the e-Aadhaar PDF that UIDAI itself gives citizens, and the app crashes. That is
a demo-day landmine independent of everything else in this document.

### 2.2 The correct mechanism

A signed PDF carries a **PKCS#7 / CMS `SignedData` blob** embedded in a signature
dictionary, under an ISO 32000 / ETSI **PAdES** profile. Verification is *not* "is there a
signature object". It is a chain of six distinct checks, and skipping any one of them is a
known, published attack.

**(a) Cryptographic validity.** Extract the `/Contents` hex string (the DER-encoded CMS),
recompute the message digest over the byte ranges named in `/ByteRange`, and verify the
signature against the signer certificate's public key.

**(b) Byte-range coverage — the check people skip.** `/ByteRange` is `[a b c d]`: it covers
`[a, a+b)` and `[c, c+d)`, with the gap being the `/Contents` placeholder itself. Two
failure modes:

- If `c+d < filesize`, there are **bytes after the signed region**. PDF permits *incremental
  updates* — appended revisions that override earlier objects. An attacker takes a
  legitimately signed document, appends a revision that redefines the page content stream or
  overlays an annotation, and the original signature still verifies over the original bytes
  while the *rendered* document says something different. This is the **Incremental Saving
  Attack (ISA)**; the **Shadow Attack** family (hide / replace / hide-and-replace) is its
  refined form, where the signer is tricked into signing a document containing dormant
  content that is later activated. **[VERIFY]** the exact taxonomy if you cite it — it comes
  from the Ruhr-Universität Bochum work (Mladenov et al., "1 Trillion Dollar Refund", CCS
  2019; "Shadow Attacks on PDF", NDSS 2021).
- **Signature Wrapping (SWA)**: the attacker relocates the real signed content and points
  `/ByteRange` at it, while the visible document body is attacker-controlled.
- **Universal Signature Forgery (USF)**: a malformed or empty signature dictionary that
  causes lax viewers to render a green "signed" badge without performing verification.
  The lesson: **never treat "a signature object is present" as "the signature is valid"**,
  and never trust a viewer's badge as your verification result.

Your acceptance criterion should be `SignatureCoverageLevel.ENTIRE_FILE`. Anything less is
reported to the user, not silently accepted.

**(c) Certificate chain.** Build a path from the signer certificate to a trust anchor you
pinned. For Indian government documents the anchor is the **CCA India Root Certifying
Authority (RCAI)** hierarchy — issuer CAs licensed under the IT Act 2000. **[VERIFY]** which
specific licensed CA currently issues UIDAI's e-Aadhaar signing certificate; this has changed
over time across (n)Code Solutions, e-Mudhra and NSDL/Protean, and the correct answer is
"whatever is in the certificate we pinned", not a name from memory. Do not trust the OS
store — it does not include RCAI by default on most systems.

**(d) Revocation.** CRL or OCSP. In an offline demo you almost certainly cannot fetch these.
That is fine — but **state the policy explicitly** in your output ("revocation not checked;
offline mode") rather than silently passing. A signature from a revoked cert that you report
as valid is exactly the kind of thing a security-literate judge probes for.

**(e) Signing time.** `/M` in the signature dictionary is **self-asserted by the signer and
carries no cryptographic weight**. Only an embedded RFC 3161 timestamp token, itself
verified against a trusted TSA, gives you a defensible signing time. If there is no
timestamp, you can check that the signing cert was within its validity window *at
verification time*, and say nothing stronger.

**(f) DocMDP / permissions.** A certification signature (`/DocMDP`) declares what later
changes are permitted (P=1 no changes, P=2 form-fill, P=3 form-fill + annotations). Check
that any incremental updates present are within the declared permission level.

### 2.3 e-Aadhaar and DigiLocker specifics

**e-Aadhaar PDF.** Downloaded from the UIDAI portal, it is **password-protected**; the
conventional password is the first four letters of the name in capitals plus the four-digit
birth year (e.g. `VEDJ1998`). **[VERIFY]** the current rule. This means your endpoint needs
an optional `pdf_password` form field, and you must not log it. The PDF carries a UIDAI
digital signature; it also carries the Secure QR as an embedded image, so once opened you
get **two independent crypto anchors from one file** — the PDF signature and the QR
signature. That is a genuinely strong demo.

**DigiLocker "Issued Documents."** These are pulled directly from the issuer and carry the
issuer's digital signature. **[VERIFY]** the exact legal citation before you quote it — the
commonly cited basis is Rule 9A of the Information Technology (Preservation and Retention of
Information by Intermediaries Providing Digital Locker Facilities) Rules, 2016, read with
§§ 4 and 7A of the IT Act 2000, treating issued documents as at par with originals. Uploaded
DigiLocker PDFs also carry a QR that resolves to a DigiLocker verification URL — but note
that following that URL is an *online* check, which is outside your stated scope, and the QR
alone proves nothing offline (anyone can print a QR pointing at a URL).

Important boundary: **verifying a DigiLocker-issued PDF offline is legitimate and needs no
registration. Pulling documents from the DigiLocker API is a Requester-Organisation
integration and does require onboarding.** Do not blur these in your pitch.

### 2.4 Is it worth adding for this hackathon?

**Yes — it is the second-highest-value item in this document**, for four reasons:

1. It is a *real* Tier-1 cryptographic result, not a heuristic, and it extends your strongest
   claim from "Aadhaar cards photographed well enough to decode the QR" to "any
   DigiLocker-issued document, including marksheets" — which is precisely the category
   currently stuck at `UNVERIFIABLE` forever.
2. It answers "how does this generalise beyond Aadhaar?" with a mechanism instead of a
   roadmap slide.
3. It fixes the HTTP 500 described above.
4. It lets you demonstrate a **detected** attack live: sign a PDF, append an incremental
   update that changes a visible field, and show your validator reporting
   `SIGNATURE_DOES_NOT_COVER_WHOLE_FILE` while Chrome's PDF viewer still shows a signature.
   That is a far more memorable demo than an ELA heatmap.

### 2.5 Minimal implementation

Use **pyHanko** (`pyhanko` + `pyhanko-certvalidator`). It is the only mature Python library
that handles coverage levels and the incremental-update attack class correctly; rolling your
own `/ByteRange` parser is how you end up shipping the USF bug.

```
pyhanko==0.25.*            # [VERIFY] current version at build time
pyhanko-certvalidator
pymupdf                    # NOTE: already imported at main.py:25, missing from requirements
```

New module, roughly 120 lines, shape only:

```python
# pdf_signature.py  (sketch — not code to paste blindly)
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.diff_analysis import SuspiciousModification
from pyhanko_certvalidator import ValidationContext

def verify_signed_pdf(pdf_bytes, password=None, trust_roots=...):
    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    if reader.encrypted:
        reader.decrypt(password)          # e-Aadhaar path
    sigs = reader.embedded_signatures
    if not sigs:
        return ["PDF_NO_SIGNATURE"]       # absence, NOT failure
    vc = ValidationContext(trust_roots=trust_roots,
                           allow_fetching=False,   # offline demo
                           revocation_mode="soft-fail")
    codes = []
    for sig in sigs:
        status = validate_pdf_signature(sig, vc)
        codes.append("PDF_SIG_INTACT" if status.intact else "PDF_SIG_BROKEN")
        codes.append("PDF_SIG_TRUSTED" if status.valid and status.trusted
                     else "PDF_SIG_UNTRUSTED_CHAIN")
        if status.coverage != SignatureCoverageLevel.ENTIRE_FILE:
            codes.append("PDF_SIG_PARTIAL_COVERAGE")   # incremental-update attack
        if status.modification_level is SuspiciousModification:
            codes.append("PDF_SIG_SUSPICIOUS_MODIFICATION")
        codes.append("PDF_SIG_TIMESTAMPED" if status.timestamp_validity
                     else "PDF_SIG_NO_TRUSTED_TIMESTAMP")
        codes.append("PDF_SIG_REVOCATION_NOT_CHECKED")  # honest, offline
    return codes
```

Then in `verdict.py`, add to `TIER_OF_REASON` (`verdict.py:126-152`):

- `PDF_SIG_BROKEN`, `PDF_SIG_PARTIAL_COVERAGE`, `PDF_SIG_SUSPICIOUS_MODIFICATION`,
  `PDF_SIG_UNTRUSTED_CHAIN` → `Tier.CRYPTOGRAPHIC`, added to `FATAL_CRYPTOGRAPHIC`
  (`verdict.py:154`).
- `PDF_SIG_INTACT` **and** `PDF_SIG_TRUSTED` **and** `ENTIRE_FILE` coverage together →
  a passing cryptographic result. Do not let `PDF_SIG_INTACT` alone into
  `PASSING_CRYPTOGRAPHIC` — intact-but-untrusted-chain is a self-signed forgery.
- `PDF_NO_SIGNATURE` → not a failure. It means "no Tier 1 available", i.e. fall through to
  `UNVERIFIABLE`. Getting this distinction right is itself worth saying out loud.

Effort: **half a day to a day**, including the deliberately-tampered demo PDF.

---

## 3. The printed-paper path

This is the hard case and you should treat it as the intellectual core of your pitch,
because it is where honest engineering separates you from teams showing green ticks.

### 3.1 What survives a print-scan cycle, and what is destroyed

A print-then-photograph cycle is a **lossy analogue round trip**: rasterise → halftone →
ink on paper → ambient illumination → lens → sensor → demosaic → JPEG. Every digital-domain
forensic trace is annihilated. What survives is only what was designed to survive: content
encoded redundantly enough to be re-read optically.

| Signal | Survives? | Why |
|---|---|---|
| **Cryptographic signature inside a 2D barcode** (Aadhaar Secure QR) | **Yes** | Reed–Solomon error correction is designed for exactly this. Recovered bytes are bit-exact or the decode fails outright. This is the *only* strong signal that survives. |
| Checksums on printed numbers (Verhoeff) | Yes, if OCR is correct | Survives as text. But OCR error is now part of your threat model — a misread digit fails Verhoeff on a genuine card. |
| Internal arithmetic consistency (marks vs total) | Yes, if OCR is correct | Same caveat, amplified: OCR on tabular data is far less reliable than on a 12-digit number. |
| Layout / template geometry | Partially | Survives, but perspective, skew and lens distortion require rectification you do not currently do. |
| Physical security features — microtext, guilloche, UV ink, holograms, intaglio | **Partly, and you cannot use them** | Microtext and guilloche survive on the paper but need >1200 dpi flatbed capture to resolve. UV and IR features need non-visible-spectrum illumination. A phone camera captures none of this. Aadhaar "cards" are also commonly plain-paper home prints, so their absence proves nothing. |
| **JPEG-domain forensics: ELA, quantisation-table analysis, JPEG ghosts, double-quantisation, PRNU/sensor noise, CFA artefacts, metadata/EXIF** | **Destroyed** | See below. This is the whole family. |
| Copy-move / resampling detection | Destroyed | Halftoning plus optical blur plus a fresh single compression removes the resampling signature. |

### 3.2 ELA on a print-scan: assessment of `ela.py`

**Verdict: on a photographed printed document, ELA has no evidentiary value whatsoever, and
`ela.py` reports `applicable=True` in precisely that case.**

The argument, from `ela.py`'s own stated mechanism (`ela.py:4-13`): ELA detects *differing
compression histories between regions of one image*. It works when a JPEG was decoded,
locally edited, and re-encoded — the edited region has one fewer quantisation generation than
its surroundings.

When a document is printed and re-photographed, **the entire image has exactly one
compression history: the camera's single JPEG encode of the scene.** There is no
region-to-region history differential, because there is no digital editing in the image's
history at all — the tampering happened *before* the analogue round trip, on a different
artefact. ELA is measuring a property the attack does not touch. It is not "weak here"; it is
categorically inapplicable.

**Three specific problems with the implementation:**

**(a) The applicability gate tests the wrong thing.** `ela.py:65` gates on
`source_format not in {"JPEG","JPG","MPO"}` — i.e. the *container format*, not provenance.
A phone photo of a printed Aadhaar is a JPEG, so the code sets `applicable=True`
(`ela.py:98`) and emits a substantive reason code. The gate excludes the one input class
(PNG/screenshot) where ELA is merely useless, and admits the class (camera photo) where it
is actively misleading. The `README.md:78-80` and `ela.py:15-29` prose is admirably honest
about ELA's limits — but that honesty lives in comments a judge never reads, while the API
field named `applicable` says `true`.

**(b) The anomaly threshold is calibrated below the chance rate.**
`ela.py:43` `FLAG_SIGMA = 2.5`; `ela.py:44` `MIN_FLAGGED_FRACTION = 0.004`.
`_score_blocks` (`ela.py:131-133`) computes the mean and standard deviation of the
per-block means *of that same image* and flags blocks above `mean + 2.5σ`. For any roughly
normal distribution, the expected fraction above +2.5σ is ≈0.62%. Block-mean residual
distributions on a document are strongly right-skewed (text edges, QR modules), so the
observed exceedance rate is typically higher still. **The firing threshold (0.4%) is below
the rate you get from a perfectly clean image by construction.** `ELA_LOCALISED_ANOMALY`
(`ela.py:93`) is therefore near-certain to fire on every JPEG document you feed it — and via
`verdict.py:215-216` that produces a `NEEDS_REVIEW` verdict on genuine PAN cards and
marksheets. On stage, this reads as your system accusing a real document.

**(c) The re-save premise is only approximately true as implemented.** `ela.py:78` re-saves
at a fixed `quality=90` through Pillow, after `convert("RGB")` (`ela.py:62`). Pillow's q90
quantisation tables and chroma-subsampling choice will not match the source camera's tables.
The residual you measure is therefore dominated by *"distance between the camera's
quantisation grid and Pillow's q90 grid"* — a global property — rather than by local edit
history. The standard mitigation is to read the original quantisation tables
(`Image.quantization`) and re-save with those, or to sweep quality and look for the JPEG-ghost
minimum. Neither is done. Also note `blocks` at `ela.py:89` is bound and never used.

**Does `ela.py` make claims it cannot support?** The module docstring does not — it is one of
the more intellectually honest files in the repo. But the **API surface does**, in three
places: the field `applicable: true` on camera photos; the reason code
`ELA_LOCALISED_ANOMALY` with public text "Compression analysis shows a localised anomaly"
(`verdict.py:100`); and the fact that this code alone can drive a `NEEDS_REVIEW` verdict
despite `verdict.py:25` and `README.md:107` both stating Tier 3 is "never the sole cause of a
flag". **The code contradicts its own documented rule** — see §5.

**Recommendation.** Do not delete ELA — it is a legitimate reviewer aid on *born-digital*
uploads and it is a fair thing to show. Do three things instead:

1. Rename `applicable` → `analysis_meaningful`, and set it `False` when the image looks like
   a camera capture of a physical document (EXIF `Make`/`Model` present, or no
   `Software`/editor tag, or single-quantisation-table evidence). Cheap heuristic; huge
   honesty win.
2. Raise `MIN_FLAGGED_FRACTION` to something above the ~0.6% null rate — 0.03–0.05 is a
   defensible starting point — **and say in your writeup that you calibrated it against the
   null rate rather than picking a number.** That sentence alone is worth more than the
   feature.
3. Remove `ELA_LOCALISED_ANOMALY` from anything that can produce a verdict. Return it as a
   heatmap and a note. §5 covers this.

### 3.3 The correct pipeline for printed documents

The only defensible architecture is: **anchor on whatever cryptographic material survived
the print, and treat everything else as consistency checking that can only ever produce a
negative result.**

```
photo/scan of printed document
  │
  ├─► [1] find and decode every 2D barcode           ← the only strong signal
  │        │
  │        ├─ Aadhaar Secure QR (V2)
  │        │     ├─ verify UIDAI RSA signature over the payload     ← TIER 1
  │        │     ├─ extract signed fields: name, dob, gender, ref_id
  │        │     └─ extract the signed JPEG2000 photo
  │        │
  │        ├─ Aadhaar legacy QR (V1) → unsigned. Explicitly worthless.
  │        └─ any other QR → out of scope, do not imply meaning
  │
  ├─► [2] OCR + locate the printed photo on the card face
  │
  ├─► [3] ══ CROSS-CHECK: signed payload  vs  printed card ══      ← TIER 1.5
  │        This is the step that makes the whole thing work, and
  │        it is the step the repo is missing.
  │        ├─ signed name/dob/gender   vs  OCR'd name/dob/gender
  │        ├─ signed ref_id[0:4]       vs  last 4 of OCR'd number
  │        └─ signed QR photo          vs  photo printed on the card   (face-match)
  │
  ├─► [4] structural checks on the printed content (Verhoeff, arithmetic)   ← TIER 2
  │        NOTE: covered by NO signature. Must be able to flag independently.
  │
  ├─► [5] identity binding: signed QR photo  vs  live selfie + PAD    ← separate axis
  │
  └─► [6] heuristics (ELA, baselines) → reviewer aid only, never a verdict   ← TIER 3
```

Step **[3]** is the crux, and it is what turns a signature check into a document check. A
signature over a QR payload proves the *payload* is genuine. It becomes a statement about the
*card* only when you prove the card and the payload describe the same person. That proof is a
cross-check, and it is the thing your architecture is missing.

**Does the repo do this correctly?** Partially.

- **QR decode: yes, and it is genuinely good.** `read_qr_payloads` (`aadhaar_qr.py:107-258`)
  is the strongest engineering in the repo — multi-scale upsampling, autocontrast, Otsu and
  adaptive thresholding, plus an OpenCV `QRCodeDetector` fallback. This is exactly the right
  amount of paranoia for phone captures.
- **Signature verification: yes, structurally correct.** `aadhaar_qr.py:351-370` verifies
  SHA256-with-RSA-PKCS#1v1.5 over `data[:-256]`. The `_split_text_fields` comment
  (`aadhaar_qr.py:317-320`) about not naively splitting on `0xFF` because the JPEG2000 photo
  contains `0xFF` markers is correct and non-obvious, and the backwards photo-length
  computation (`aadhaar_qr.py:405-411`) is the right approach.
- **Cross-check [3]: entirely absent.** This is the finding in §4.
- **Trust anchor: unpinned.** `load_uidai_public_key` (`aadhaar_qr.py:481-489`) extracts
  `.public_key()` and discards the certificate — no subject check, no validity-period check,
  no fingerprint pin, no exposure in `/health`.

Two decode-layer items to verify against the current UIDAI spec, both of which fail
*silently* and both of which corrupt the extracted photo (and therefore the face-match):

- **[VERIFY]** `_expected_hash_count` (`aadhaar_qr.py:429-437`) maps
  `{"0":0,"1":1,"2":1,"3":2}` for the email/mobile-present flag. If this mapping is wrong for
  the payload version in front of you, `photo_end` (`aadhaar_qr.py:407`) is off by 32 or 64
  bytes and the JPEG2000 is truncated. The docstring admits an unknown value "silently
  corrupts the photo slice" — and then falls back to `0` **without emitting a reason code**.
  It should emit `QR_CONTACT_FLAG_UNRECOGNISED`.
- **[VERIFY]** the version-prefix detection at `aadhaar_qr.py:382`
  (`first_value.upper().startswith("V") and first_value[1:].isdigit()`). If a payload
  revision changes this, every field shifts by one position and you will render someone's
  name as their DOB.
- `verify_contact_hash` (`aadhaar_qr.py:440-459`) is **defined and never called anywhere in
  the repo.** That is a shame, because it is a genuinely useful second binding factor (see
  §7). Its iteration rule is **[VERIFY]**-grade guesswork by its own admission
  (`aadhaar_qr.py:446-448`).

### 3.4 Documents with no cryptographic anchor — the ceiling

**PAN cards and most marksheets have no offline cryptographic material.** `pan.py:11-16`
states this correctly and `README.md:71-74` repeats it. Be blunt about what follows:

**For these documents, your system can produce exactly one class of positive finding:
internal inconsistency. It cannot ever produce evidence of genuineness. Not weak evidence —
none.**

The ceiling is:

- **You can catch**: a PAN that violates the format (`pan.py:53-61`); a marksheet whose marks
  do not sum to its printed total, or exceed a stated maximum; a percentage that does not
  follow from the marks.
- **You cannot catch**: a competently produced fake. A forger who prints a
  format-valid PAN with a consistent name, or a marksheet whose arithmetic they checked in
  Excel, passes every check you have and always will. There is no signal left. This is not a
  gap in your implementation — it is a property of the documents.
- **Therefore the only honest verdict is `UNVERIFIABLE`**, and `verdict.py:35-37` and
  `README.md:114-115` say exactly this. **This is the best decision in the project.** Defend
  it loudly. When a judge says "so your PAN check doesn't do anything?", the answer is: "It
  catches structurally impossible PANs and it refuses to give you a green tick for the rest,
  because a green tick would be a lie. The only authoritative PAN check is the Income Tax
  Department's API, which requires registration we don't have."

The genuine path forward for these documents is **not better forensics — it is a
cryptographic anchor that does not exist yet on paper**: DigiLocker-issued signed PDFs
(§2.3), or issuer-side signed QR adoption by boards. Frame it that way and you are proposing
policy, which scores better than proposing a better classifier.

One warning specific to your code: because `SELECTED_SUBJECT_NOT_FOUND` is classed as a fatal
structural failure (`verdict.py:144`), **an OCR miss on a genuine marksheet produces
`STRUCTURALLY_INVALID`** — the same verdict as real tampering. And `maximum` is hardcoded to
100 per subject (`marksheet.py:334`), so any board using a different maximum triggers
`MARKS_EXCEED_MAXIMUM` → `STRUCTURALLY_INVALID` on a genuine document. **An extraction
failure must never produce a fraud-shaped verdict.** See §7 item 3.

### 3.5 Storage and handling — review of `store.py` and `config.py`

**The principle**, given you touch Aadhaar data and are not an AUA/KUA (§6): store the
minimum that lets you explain a decision, never the identifiers themselves, never biometrics,
and delete on a schedule.

**What `store.py` gets right — and this is genuinely good design.** The schema
(`store.py:24-36`) has no image column, no embedding column, no identifier column. The
reasoning at `store.py:5-8` — "a column you never populate eventually gets populated by
someone at 3am; a column that does not exist does not" — is exactly the right instinct and is
worth saying to a judge verbatim. `face_distance` is rounded to 2dp on write
(`store.py:89`); a scalar distance is not biometric data and is defensible.

**Six concrete problems.**

1. **`reason_codes` is a free-text sink, which undermines the schema argument.** Several code
   paths append raw exception strings as "reason codes":
   `face_match.py:112` → `["FACE_NOT_DETECTED", str(exc)[:120]]`;
   `face_match.py:157`; `aadhaar_qr.py:517` → `["QR_DECODE_FAILED", str(last_error)]`.
   These flow through `main.py:154` into `store.record(...)` and into the JSON column
   (`store.py:87`). DeepFace's "face could not be detected" `ValueError` conventionally
   includes the **file path** it was given — i.e. your temp directory name. So the audit
   store *can* hold arbitrary strings, and does. The schema is only as tight as what you put
   in it. **Fix: validate every reason code against `REASON_TEXT` before storing, and drop or
   bucket anything unrecognised.** ~10 lines. It also fixes the `top_reasons` aggregation
   (`store.py:116-123`), which currently counts unique exception strings as distinct
   "reasons".

2. **The response leaks a full residential address while "redacting" the least sensitive
   field.** `AadhaarQRResult.redacted()` (`aadhaar_qr.py:92-100`) masks the first four
   characters of `reference_id` and pops `photo_present`. It does **not** touch `care_of`,
   `house`, `street`, `landmark`, `location`, `vtc`, `sub_district`, `district`, `state`,
   `pincode`, `name`, or `dob` — all of which are returned to the client at `main.py:167` and
   `main.py:278` and rendered on your demo screen. The full name, date of birth and home
   address of a real teammate, on a projector, in a room of strangers. This is a far larger
   exposure than four digits, and it is the one a privacy-minded judge will notice. **Fix:
   default `redacted()` to name-initials + DOB-year + district only; put full fields behind an
   explicit `?reveal=true` that is off in demo mode.** ~20 min.

3. **No retention limit, no purge.** `config.py:12` puts `audit.sqlite3` in the working
   directory, unencrypted, growing forever. DPDP-style storage limitation is a one-liner:
   `DELETE FROM checks WHERE created_at < datetime('now','-7 days')` on startup, plus a
   `RETENTION_DAYS` env var. **This is 15 minutes and it directly answers a judge question.**

4. **`/dashboard/history` and `/dashboard/summary` are unauthenticated** (`main.py:552,557`).
   Fine for a local demo; say so rather than being caught. If you have 20 minutes, an
   env-var bearer token is enough to show you thought about it.

5. **`uidai_cert_path` is not a dataclass field.** `config.py:11` lacks a type annotation, so
   `@dataclass` treats it as a plain class attribute. It works for attribute access
   (`main.py:50`) but it is the only setting that is *not* environment-overridable, and it is
   silently excluded from the frozen-dataclass machinery. Given that this path is your entire
   root of trust, it should be `uidai_cert_path: str = os.getenv("UIDAI_CERT_PATH",
   "certs/uidai_signing.cer")`. One line.

6. **Consent gating is fail-closed and that is correct.** `config.py:19-29` defaults
   `require_consent_subject=True` with an empty subject list, so every face endpoint 403s
   until someone deliberately sets `CONSENT_SUBJECTS` (`main.py:66-84`). Good. Note that
   `/health` (`main.py:573`) exposes only a count, not names. Also good.

**What should never be persisted, and currently is not** — verify these stay true:
raw uploads, live frames, face embeddings, the JPEG2000 photo, full Aadhaar/PAN numbers,
`ocr.OCRResult.text`. All correct today.

**One caveat on the shredding claim.** `face_match._shred` (`face_match.py:269-278`)
overwrites with zeros, `fsync`s, then unlinks — and `README.md:125-127` presents this as a
privacy guarantee. On a journaling filesystem, on a copy-on-write filesystem, or on any SSD
with wear-levelling and an FTL, an in-place overwrite does **not** guarantee the original
blocks are unrecoverable. Present it as **best-effort hygiene**, not erasure. Similarly,
`face_match.py:129-130` (`id_photo = b""`, `selfie = b""`) rebinds local names only —
Python `bytes` are immutable and cannot be zeroed, and this affects nothing in the caller.
It is inert. Do not cite it as a control; a judge who knows Python will notice.

---

## 4. Forgery defences — attack-by-attack

### 4.1 Photoshopped scan of a real document (name/DOB edited)

| Document | Caught? | Why |
|---|---|---|
| Aadhaar, QR untouched | **No** | The QR still verifies → `GENUINE_SIGNED` (`verdict.py:210-212`). Nothing compares the signed `name`/`dob` against the printed ones. The attack is *invisible* to the system, and worse, the system actively endorses the document. |
| Aadhaar, QR also edited | **Yes** | Signature fails → `FORGED_SIGNATURE`. Strong. |
| PAN | **No** | Format-only (`pan.py:40-72`). Editing a name does not change the format. `cross_check_name` (`pan.py:75-98`) is a hint at best and correctly tiered heuristic (`verdict.py:151`). |
| Marksheet | **Rarely** | Only if the edited mark exceeds 100 (`marksheet.py:382-386`). The arithmetic check that *would* catch it is not implemented (§4.6). |
| ELA | **No** | §3.2. If the scan was re-photographed, no signal exists. If it is born-digital and the forger re-saves the whole file once, `ela.py:5-7`'s own premise is defeated — `README.md:24` calls this "a one-line defeat" and is right. |

**The single highest-value mitigation is the same one as §4.3: cross-check the OCR'd printed
fields against the signed QR fields.**

### 4.2 Fully synthetic / printed fake card

**Mostly caught, for Aadhaar only, and you should quantify it honestly.**

- Forger fabricates a QR payload → cannot produce a valid RSA signature without UIDAI's
  private key → `QR_SIGNATURE_INVALID` → `FORGED_SIGNATURE` (`verdict.py:206-207`). This is
  your genuinely strong result.
- Forger omits the QR entirely → `QR_NOT_FOUND` (`aadhaar_qr.py:505`). That code is **not in
  `TIER_OF_REASON`** (`verdict.py:126-152`), so it produces no tier signal and the verdict
  falls through to `UNVERIFIABLE` (`verdict.py:217-218`). Correct — absence of evidence is
  not evidence — but make sure the UI does not render `UNVERIFIABLE` as neutral-grey calm
  when the document is an *Aadhaar card with no QR on it*, which is itself suspicious for
  that document type.
- Forger prints a V1 legacy QR they authored themselves → `QR_V1_LEGACY_UNSIGNED`
  (`aadhaar_qr.py:296`), also unmapped, also → `UNVERIFIABLE`. `README.md:61-64` and
  `aadhaar_qr.py:9-12` are right that this must never show green. It does not. Good.
- A made-up 12-digit number passes Verhoeff with probability **1/10**
  (`verhoeff.py:69-82`). So the checksum catches roughly 90% of lazy fabrications and 0% of
  competent ones — a forger generates a valid number in a loop (`verhoeff.py:9-11` says so).
  Quote the 1-in-10 figure; a real number beats a hand-wave.
- PAN / marksheet: **not caught.** No anchor. §3.4.

### 4.3 THE REPLAY ATTACK — genuine QR, different photo and name

*A forger copies a real person's genuine Aadhaar Secure QR onto a card bearing a different
photo and name. The signature verifies perfectly.*

**This is the most important attack in your threat model, it is the direct answer to "can't a
forger just copy real numbers or QR codes?", and the repository does not defend against it.**

The defence requires two things, both of which the data already contains and neither of which
the code performs:

**(a) Compare the signed QR photo against the photo printed on the card. — NOT DONE.**

`main.py:221-231`:

```
if back_bytes is not None:
    face_source = front_bytes            # ← the PRINTED card image
elif qr_result.photo_jp2 is not None:
    face_source = qr_result.photo_jp2    # ← the SIGNED photo (legacy path only)
else:
    face_source = front_bytes
```

The `back_document` path is the documented normal path for current two-sided Aadhaar cards
(`main.py:191-199`). On that path the live selfie is compared against the **printed** card
photo. A forger who prints their own face on the card and a genuine stranger's QR on the back
gets:

- `QR_SIGNATURE_VALID` → `GENUINE_SIGNED`, headline **"Issuer-signed and unaltered"**
  (`verdict.py:171`)
- `FACE_MATCH` against their own printed photo → `identity_binding: BOUND`
- The response even labels it `"face_source": "printed_front"` (`main.py:275`) — the code
  reports its own weakness accurately while the verdict says the opposite.

**Full pass on both axes, for a forged card.** This is the exact failure `README.md:150-154`
claims to have designed around, and `face_match.py:5-10` claims to close. The signed photo
is decoded (`aadhaar_qr.py:411,424`) and reported as available (`main.py:168`) — and then
not used.

**(b) Cross-check the OCR'd printed fields against the signed QR fields. — NOT DONE
ANYWHERE.**

`main.py:138-143` calls `ocr.extract_text` for one purpose only: pulling a 12-digit number to
feed Verhoeff. Nothing compares:

- OCR'd name vs `qr_result.fields["name"]`
- OCR'd DOB vs `qr_result.fields["dob"]` (`ocr.py:40-46` already extracts dates and years)
- OCR'd gender vs `qr_result.fields["gender"]`
- **the last four digits of the OCR'd Aadhaar number vs `reference_id[0:4]`** — the code
  already knows that `reference_id` begins with the last four digits
  (`aadhaar_qr.py:97`), and `main.py:138-143` already has both values in scope. This is a
  four-line check that is currently not written.

**And (c): even if you fixed the structural checks, the verdict engine would swallow them.**
`verdict.py:206-218` evaluates `crypto_pass` before `structural_fail` and returns
immediately. A printed number that fails Verhoeff — the exact fingerprint of a transplanted
QR — is demoted to the `advisory` list (`verdict.py:222`) under a `GENUINE_SIGNED` headline.
So the replay fix requires the §5 verdict fix as well; they are one change.

**What to build (highest-value work in this document):**

```
1. face_source = qr_result.photo_jp2 whenever it exists — always, both paths.
   Fall back to the printed front ONLY when there is no signed photo,
   and emit FACE_SOURCE_UNSIGNED so the verdict can down-rank it.

2. New check — signed photo vs printed card photo:
      compare_faces(qr_result.photo_jp2, front_bytes)
   Mismatch → CARD_PHOTO_MISMATCHES_SIGNED_PHOTO.  Tier CRYPTOGRAPHIC-adjacent,
   FATAL.  This is the replay detector.

3. New check — signed fields vs OCR'd fields:
      name (normalised, fuzzy),  dob,  gender,
      reference_id[0:4] vs last 4 of the OCR'd number.
   Mismatch → CARD_FIELDS_MISMATCH_SIGNED_PAYLOAD.  FATAL structural.

4. New verdict: SIGNED_PAYLOAD_TRANSPLANTED —
   "The QR is genuine and issued by UIDAI, but it does not belong to this card."
```

That fourth verdict is the single best slide in your deck. It is a *specific, named,
demonstrable* attack that you detect and most systems do not, and it converts your hardest
judge question from a weakness into your headline.

Note that item 2 also gives you a real demo: hold up a genuine card, then hold up the same
card photocopied with a different photo pasted on, and show the verdict flip from
`GENUINE_SIGNED` to `SIGNED_PAYLOAD_TRANSPLANTED` while the signature stays valid in both.

**Residual limit to state honestly:** if the forger transplants a stranger's QR *and* also
prints that stranger's photo — i.e. impersonates the actual QR owner — then the card is
internally consistent and only the *live selfie* fails. That is correct behaviour: you get
`GENUINE_SIGNED` + `NOT_BOUND`, which is the true state of the world. Keeping those axes
separate (`verdict.py:67-71`, `README.md:118-122`) is the right architecture and you should
say so.

### 4.4 Presentation attack on the face-match — is the liveness real?

**Assessment: it is a weak but non-zero challenge–response check. It is not liveness
detection. It is roughly one-third of the way to theatre, and the repo already says so, which
is to your credit.**

What `check_liveness` (`face_match.py:133-194`) actually does: runs MediaPipe Face Mesh over
≥3 frames (`face_match.py:207-226`) and requires either an eye-aspect-ratio dip below 0.18
that also recovers (`face_match.py:176-179`) or a normalised nose-offset change ≥0.12
(`face_match.py:169-173`).

| Attack | Defeated? |
|---|---|
| Single still photo held to the camera | **Yes.** EAR is constant across frames; `closed < 0.18 < opened` (`face_match.py:179`) cannot hold. This is genuinely worth something. |
| Two printed photos (open eyes / closed eyes) swapped between frames | **No.** The check is per-frame geometry with no temporal or texture model. |
| Phone/laptop screen replaying a video of the victim | **No.** Real blinks, real head turns. No moiré, reflectance, or screen-bezel detection. |
| Printed mask / cut-out with eye holes | **No.** |
| Deepfake / face-swap video stream | **No.** |
| Injection attack (virtual camera feeding frames straight to the API) | **No — and it is trivial here.** The endpoint takes uploaded image files (`main.py:493`). There is no capture attestation, no server-issued challenge nonce, no timing constraint, no frame-ordering check, no session binding. An attacker uploads three prepared JPEGs. |

**The injection point is the real problem and it is architectural, not a tuning issue.** The
API cannot distinguish "frames from a live camera" from "three files on disk", because it
receives files either way. Real PAD systems address this with a server-issued randomised
challenge (blink *now*, turn left *then* right, in an order the server picks per session),
short server-side timing windows, and ideally SDK-level capture attestation. Even the
cheapest version — server issues a random challenge sequence, client must return frames
satisfying it in order, within N seconds, tied to a one-time token — would materially raise
the bar. Currently `challenge` is chosen by the *client* (`main.py:496`), which inverts the
security property entirely.

**Two implementation bugs in this area:**

1. **The frame-count guard is in the wrong place.** `main.py:243-247` checks
   `len(frame_bytes) < 3` **after** `check_liveness` (`main.py:233`) and `compare_faces`
   (`main.py:236-239`) have already run. `main.py:239` indexes
   `frame_bytes[len(frame_bytes)//2]`, which on an empty list raises `IndexError` → HTTP 500
   instead of the intended 400. `/verify/face` (`main.py:503-507`) gets the ordering right;
   `/verify/aadhaar-full` does not. Move it to immediately after `main.py:208`.
2. **A failed face-match is reported as "not attempted".** `_binding`
   (`verdict.py:232-239`) returns `NOT_ATTEMPTED` when `face_matched is None` — but
   `is_match` is `None` for `FACE_NOT_DETECTED` and `FACE_MATCH_ERROR` too
   (`face_match.py:105-123`). So an attacker supplying a card whose photo cannot be detected
   gets `GENUINE_SIGNED` + `NOT_ATTEMPTED`, which reads as "we didn't check" rather than "we
   checked and it failed". That is the replay attacker's ideal output. **Add
   `Binding.CHECK_FAILED`.** ~15 min.

**What to say to a judge:** `face_match.py:23-30` already contains the right answer — name
the attack, do not claim to stop it. Add the injection point to that list; volunteering the
attack a reviewer was about to raise is worth more than a defence you do not have.

### 4.5 Deepfake / AI-generated ID images

**Nothing in the repository addresses this.** No PAD model, no generated-image detector, no
frequency-domain or diffusion-artefact analysis. `MODEL_NAME = "ArcFace"`
(`face_match.py:44`) is a recognition model; it will happily match a high-quality synthetic
face to its target, because matching is exactly what it was trained to do.

**But you have the correct structural answer, and it is stronger than any detector:**

> "A generative model can produce a photorealistic Aadhaar card. It cannot produce a valid
> UIDAI RSA signature over the payload, because that needs UIDAI's private key. So a fully
> AI-generated Aadhaar fails our Tier 1 check outright — not because we detect that it's
> AI-generated, but because it isn't signed. That's a much more durable defence than an
> AI-detector, which is in an arms race it loses. Where we *are* exposed is a deepfake
> selfie replayed against a genuine card, and we don't claim to stop that."

That answer holds up under follow-up, which a "we use an AI-detection model" answer does
not. **Do not build a deepfake detector for this hackathon.** You cannot validate it in the
time available, an unvalidated classifier is an overclaim, and the crypto argument is better.

Two things worth noting if pressed: (i) AI-generated-image detectors degrade sharply after a
print-scan cycle for the same reason ELA does — the artefacts they key on are digital-domain;
(ii) the ISO/IEC 30107-3 PAD framework is the standard to cite if a judge wants to know what
"real" liveness certification looks like. **[VERIFY]** the current part/edition before
quoting it.

### 4.6 Summary table — attack vs current defence

| Attack | Detected today? | Where it fails | Fix effort |
|---|---|---|---|
| Fabricated QR payload | **Yes** | — | — |
| Edited scan, QR untouched | **No** | No signed-vs-printed field cross-check | ~4h |
| **Transplanted genuine QR (replay)** | **No** | `main.py:221-223`; no cross-check; `verdict.py:210` | **~6h — do this first** |
| Genuine card, wrong holder | Yes (as `NOT_BOUND`) | Correct today, *if* the signed photo is used | — |
| Printed-photo presentation attack | Yes | — | — |
| Screen/video replay | No | No PAD; `face_match.py:193` admits it | Out of scope; be honest |
| Frame injection via API | No | No challenge nonce or capture attestation | ~3h for a nonce |
| Deepfake selfie | No | No PAD | Out of scope; use the crypto argument |
| Fake PAN | No (by design) | No anchor exists | Impossible — say so |
| Fake marksheet, arithmetic edited | **No** | `TOTAL_MISMATCH` never emitted (`marksheet.py`) | ~4h |
| Marksheet, mark > 100 | Yes | — | — |
| Self-signed cert dropped into `certs/` | **No** | `aadhaar_qr.py:481-489`, no pin | ~30 min |

---

## 5. Verdict semantics — is the tiering honest?

**The design is genuinely good. The implementation has three specific holes, each of which
produces an output stronger than the evidence supports.**

### What is right, and worth defending

- Refusing to average a proof and a heuristic into one score (`verdict.py:6-13`) is correct
  and unusually mature for a hackathon. Say this to judges; most teams ship a weighted score.
- Refusing to use the word "verified" (`verdict.py:28-30`) is correct.
- `UNVERIFIABLE` as the honest terminal state for PAN and marksheets (`verdict.py:35-37`) is
  correct and is your best answer to "is this real verification?".
- Separating `identity_binding` onto its own axis (`verdict.py:67-71`, `main.py:92`) is
  correct and is the right shape for the replay question.

### Hole 1 — a valid signature suppresses structural failures (CRITICAL)

`verdict.py:206-218`. Control flow is `crypto_fail → crypto_pass → structural_fail →
heuristic`. Once `crypto_pass` is truthy the function returns `GENUINE_SIGNED` and
`structural_fail` is **never inspected**; every structural code lands in `advisory`
(`verdict.py:222`).

Concretely: valid QR + printed Aadhaar number failing Verhoeff → headline **"Issuer-signed
and unaltered"** (`verdict.py:171`) with `AADHAAR_VERHOEFF_FAILED` in a secondary list.

The justification at `verdict.py:209-211` — "the signature covers these exact bytes, so ELA
noise on a photo of a signed document tells you about the camera, not the document" — is
sound **for ELA** and **unsound for anything read off the card**. The signature covers the QR
payload. It does not cover the printed number, the printed name, the printed photo, or the
printed DOB. Suppressing findings about *unsigned* regions on the strength of a signature over
a *different* region is exactly the reasoning error that makes the replay attack work.

**Fix:**
1. Rename the verdict to make its scope explicit: `GENUINE_SIGNED` → `QR_PAYLOAD_GENUINE`,
   headline "QR payload is issuer-signed and unaltered". Or keep the name and change the
   headline. Either way the user must not read "the document is genuine".
2. Partition Tier 2 into **signature-covered** (nothing today) and **not-covered** (Verhoeff
   on the printed number, arithmetic, all cross-checks). A crypto pass demotes the first and
   **must never demote the second**.
3. Add the composite verdict `SIGNED_PAYLOAD_TRANSPLANTED` (§4.3): crypto passes **and** a
   not-covered cross-check fails.

### Hole 2 — ELA alone produces a verdict, contradicting the documented rule

`verdict.py:24-26` states Tier 3 is "Advisory only. Never the sole cause of a flag."
`README.md:107` repeats it. `verdict.py:215-216` does the opposite:

```
elif heuristic_flags:
    verdict, decided_by, primary = Verdict.NEEDS_REVIEW, Tier.HEURISTIC, heuristic_flags
```

A clean PAN card whose only finding is `ELA_LOCALISED_ANOMALY` returns `NEEDS_REVIEW`,
headline "Needs human review" (`verdict.py:175`), `decided_by: heuristic` — a Tier-3 signal
solely determining a verdict. Combined with §3.2(b) — the flag threshold sitting below the
statistical null rate — **most genuine JPEG PAN cards and marksheets will return
`NEEDS_REVIEW`**, and the reason will be a compression artefact on printed text that
`ela.py:22-23` and `README.md:180-184` both already identify as ELA's known failure mode.

**Fix (two lines):** delete the `elif heuristic_flags` branch. Heuristic codes go to
`advisory` and the verdict becomes `UNVERIFIABLE`; surface the heatmap alongside it. If you
want a review flag, make it a separate boolean field (`review_suggested: true`) rather than a
verdict — because "Needs human review" reads to a user as an accusation, and you cannot
support one.

### Hole 3 — extraction failure produces a fraud-shaped verdict

`SELECTED_SUBJECT_NOT_FOUND` is tiered `STRUCTURAL` and is in `FATAL_STRUCTURAL`
(`verdict.py:144`, `verdict.py:156-158`). It is emitted whenever fuzzy subject matching scores
below 0.65 (`marksheet.py:308,323-325`). So **a genuine marksheet that Tesseract read poorly
returns `STRUCTURALLY_INVALID`, headline "Structurally invalid"** — identical to a real
tampering finding. Same for `MARKS_EXCEED_MAXIMUM` when a board's per-subject maximum is not
the hardcoded 100 (`marksheet.py:334`).

**Fix:** create a third category alongside pass/fail — `INSUFFICIENT_EXTRACTION` — mapped to
`UNVERIFIABLE` with a distinct message ("we could not read this document reliably enough to
check it"). Never let an OCR miss render as a fraud signal.

### Hole 4 — the README's marquee marksheet check is not implemented

`TOTAL_MISMATCH` and `PERCENTAGE_MISMATCH` are declared (`marksheet.py:39-40`), textualised
(`verdict.py:94,96`), tiered fatal (`verdict.py:141-142`), and named in `structural_problems`
(`marksheet.py:465-466`) — but **appear at no `result.reasons.append(...)` site anywhere in
`marksheet.py`.** `printed_total` and `printed_percentage` stay `None` (`marksheet.py:62-64`);
`analyse` sums the five selected subjects against a hardcoded max of 100 each
(`marksheet.py:404-416`) and never parses the printed total off the sheet, so no comparison
is possible.

`README.md:82-85` calls this "a real, explainable catch, and it is what to put on screen when
a judge says 'show it catching a fake, live.'" **That demo cannot currently run.** Find out
now, not on stage.

### Hole 5 — tier labels in the API are wrong for unmapped codes

`_describe` (`verdict.py:179-184`) defaults any code absent from `TIER_OF_REASON` to
`Tier.HEURISTIC`. Unmapped codes include `QR_NOT_FOUND`, `QR_DECODE_FAILED`,
`QR_V1_LEGACY_UNSIGNED`, `UIDAI_CERT_NOT_CONFIGURED`, every `FACE_*` and `LIVENESS_*` code,
and every raw exception string. So the API labels "UIDAI public certificate not loaded" as a
*heuristic* finding. The verdict logic is unaffected (`.get()` returns `None`, and
`None is Tier.HEURISTIC` is `False`, so these correctly stay out of `heuristic_flags` at
`verdict.py:200-204`) — but the displayed tier is wrong, and tier is the thing your whole
pitch rests on. **Fix:** add a `Tier.INFORMATIONAL`, map every code explicitly, and add a test
that fails when any code in `REASON_TEXT` is missing from `TIER_OF_REASON`.

### Does any weak signal produce an output a judge would read as strong?

Yes, in three places, ranked:

1. **`GENUINE_SIGNED` / "Issuer-signed and unaltered" on a replayed QR** — a judge and a user
   both read this as "this document is genuine". It means only "these QR bytes are genuine".
   §4.3.
2. **`NEEDS_REVIEW` from ELA alone on a genuine document** — overclaims in the accusatory
   direction. Hole 2.
3. **`STRUCTURALLY_INVALID` from an OCR miss** — same, on marksheets. Hole 3.

The `disclaimer` string (`main.py:35-39`) is a good control and shipping it in every response
body rather than in frontend copy is the right instinct. But a disclaimer does not repair a
verdict word. Fix the words.

---

## 6. Legal and policy position

**I am not a lawyer and this is not legal advice.** Everything below is marked for
verification where it turns on a specific section number or a commencement date. Have someone
qualified confirm before you present — and note that `README.md:167-169` already tells you to,
which is the right instinct.

### The statutory picture

- **Aadhaar Act 2016, §57** permitted the State, body corporates and persons to use Aadhaar
  to establish identity "pursuant to any law, or any contract to that effect."
- In **Justice K.S. Puttaswamy (Retd.) & Anr. v. Union of India (2018)** — the Aadhaar
  judgment, five-judge bench, 26 September 2018 — the Supreme Court **struck down §57 to the
  extent it permitted use by body corporates and individuals on the basis of a contract**.
  The practical effect: private entities lost the contractual route to Aadhaar
  authentication. **[VERIFY]** the precise reported citation before quoting it in writing.
- The **Aadhaar and Other Laws (Amendment) Act, 2019** then created a statutory route back:
  voluntary Aadhaar use, with **offline verification** as a defined mechanism and a defined
  category of **Offline Verification-Seeking Entity (OVSE)** carrying specific duties.
  **[VERIFY]** the section numbers (commonly cited: §§ 4, 8A, and the definitions in §2) —
  do not quote numbers from memory.
- The **Aadhaar (Authentication and Offline Verification) Regulations, 2021** govern the
  permitted offline verification modes. **[VERIFY]** the enumerated list; it conventionally
  includes QR-code verification, Aadhaar Paperless Offline e-KYC (the share-code XML),
  e-Aadhaar, and offline paper-based verification.
- The **Aadhaar (Sharing of Information) Regulations, 2016** restrict sharing: core biometric
  information shall not be shared, and the Aadhaar number shall not be published or displayed
  publicly.
- The **Digital Personal Data Protection Act, 2023** applies to the personal data you process
  regardless of the Aadhaar-specific rules: notice, consent, purpose limitation, data
  minimisation, storage limitation, erasure, and security safeguards. **[VERIFY]** the
  commencement status of the Act and its Rules as at your demo date — the Act was enacted in
  August 2023 with provisions to be brought into force by notification, and draft Rules were
  published for consultation. Do not assert it is or is not in force without checking.
- Offences under the Aadhaar Act include impersonation, providing false demographic
  information, unauthorised access to the CIDR, and unauthorised disclosure of identity
  information. **[VERIFY]** section numbers (conventionally §§ 34–38, with §29 governing
  restrictions on sharing).

### The boundary — what a non-AUA/KUA entity may and may not do

| **May** | **May not** |
|---|---|
| Accept an artefact the **holder voluntarily gives you**, with informed consent for a stated purpose | Perform online authentication against the CIDR (1:1 demographic or biometric) — that requires being an AUA/KUA |
| **Verify the UIDAI digital signature offline** on a Secure QR, an Offline eKYC XML, or an e-Aadhaar PDF, using UIDAI's published certificate | Perform e-KYC — retrieving demographic data from UIDAI |
| Read the demographic fields the holder disclosed, for the stated purpose only | **Store the Aadhaar number.** An OVSE is barred from collecting, using or storing the Aadhaar number **[VERIFY]** the exact regulation. Store the reference ID / last-4 only if you must. |
| Verify a **DigiLocker-issued signed document** the user uploaded | Pull documents from the DigiLocker API — that is a Requester-Organisation integration requiring onboarding |
| Compare a live selfie to the photo in the signed payload, **locally, with consent, discarding immediately** | Collect or store Aadhaar **core biometrics** (fingerprint/iris). Note: a face photo from the QR is *demographic* data the holder disclosed, not CIDR core biometric — but treat it with the same care. |
| Say "the signature verifies" | Say "verified by UIDAI" / "verified by the Government of India". You are verifying a signature, not acting as or for UIDAI. |
| Publish/display **masked** or reference identifiers | Publish or display the Aadhaar number |

### The paragraph to say out loud

> "We're not an AUA or a KUA, and we don't query the CIDR — we make no calls to UIDAI at all.
> We operate purely on the **offline verification** route the Aadhaar Act contemplates after
> the 2019 amendment: the holder voluntarily gives us an artefact they already possess — the
> Secure QR on their own card, or an offline eKYC XML they downloaded with their own share
> code — and we verify UIDAI's digital signature on it against UIDAI's published certificate.
> That proves the data was issued by UIDAI and hasn't been altered. Section 57 of the Aadhaar
> Act, which used to let private parties use Aadhaar under a contract, was struck down by the
> Supreme Court in Puttaswamy in 2018, so we don't rely on it — offline signature
> verification with the holder's consent isn't authentication and doesn't need that route. On
> the data side we follow DPDP principles as a design constraint: explicit consent from named
> subjects enforced in code, purpose limitation, and data minimisation — we store no images,
> no biometric templates, and no full Aadhaar numbers, only a verdict and reason codes. We're
> deliberately not storing the Aadhaar number at all, because an offline verification entity
> isn't permitted to. And we'd get formal legal review before this touched a real user — we're
> a student team, and we'd rather say that than pretend we've cleared it."

Three things that paragraph does: it names the case and the section (credibility), it draws
the AUA/KUA boundary *before* being asked (defuses the attack), and it ends with a limit
(defensible). **[VERIFY]** the italicised specifics — particularly the 2019 amendment section
numbers and the storage prohibition — before you say them.

### Two things you must fix to make this paragraph true

1. **"We store no full Aadhaar numbers" — verify this.** `ocr.extract_text` puts the full
   12-digit number into `OCRResult.aadhaar_numbers` and `OCRResult.text` (`ocr.py:551-558`)
   and `main.py:138` holds it in memory. It is *not* returned in the response and *not*
   passed to `store.record` — so the claim holds today. But it holds by accident of what the
   endpoint happens to return, not by construction. One careless addition to the `details`
   dict at `main.py:159-179` breaks it. Add a test.
2. **"We minimise data" — currently false at the API boundary.** The full name, DOB and
   complete residential address from the signed payload are returned to the client
   (`main.py:167`, `main.py:278`) because `redacted()` only masks four characters of
   `reference_id` (`aadhaar_qr.py:92-100`). §3.5 item 2. Fix before you say the sentence.

---

## 7. Ranked improvements

Effort assumes one person. "Judge question" is the question each item lets you answer well.

| # | Change | Effort | Why it raises the score | Answers |
|---|---|---|---|---|
| **0** | **Make the repo run.** Create the `app/` package with `services/` (or flatten the imports at `main.py:30-31`), add `pymupdf` to `requirements.txt`, and either write `tests/test_core.py` or remove the `README.md:26` reference. | 1h | A demo that doesn't start scores zero. This is not optional and everything below depends on it. | — |
| **1** | **Close the QR-replay loop.** (a) Always use `qr_result.photo_jp2` as the face source (`main.py:221-231`). (b) Add signed-photo vs printed-card-photo comparison → `CARD_PHOTO_MISMATCHES_SIGNED_PHOTO`. (c) Add signed-fields vs OCR'd-fields cross-check incl. `reference_id[0:4]` vs last-4 of the OCR'd number → `CARD_FIELDS_MISMATCH_SIGNED_PAYLOAD`. (d) New verdict `SIGNED_PAYLOAD_TRANSPLANTED`. | 6h | Converts your hardest question into your headline. Makes `README.md:150-154` true. Gives you a live demo where the signature stays valid and the verdict still flips. | **"Can't a forger just copy real numbers or QR codes?"** |
| **2** | **Fix the verdict engine.** Stop `crypto_pass` short-circuiting `structural_fail` (`verdict.py:206-218`); split Tier 2 into signature-covered vs not-covered; rename `GENUINE_SIGNED` or its headline to name its scope. | 2h | Without this, #1's new checks are silently demoted to advisory. #1 and #2 are one change. | "What exactly does your green result mean?" |
| **3** | **Delete the `elif heuristic_flags` branch** (`verdict.py:215-216`) and raise `MIN_FLAGGED_FRACTION` (`ela.py:44`) above the ~0.6% null rate. | 30min | Removes a documented-rule violation and stops your system accusing genuine documents on stage. Highest score-per-minute item in the list. | "Why did it flag a real card?" |
| **4** | **Implement the marksheet total check** for real: parse the printed total and percentage, emit `TOTAL_MISMATCH` / `PERCENTAGE_MISMATCH`. Retier `SELECTED_SUBJECT_NOT_FOUND` and hardcoded-max `MARKS_EXCEED_MAXIMUM` out of `STRUCTURALLY_INVALID` into an `INSUFFICIENT_EXTRACTION` → `UNVERIFIABLE` path. | 4h | The README's designated "catch a fake live" moment currently cannot run. Also stops false accusations from OCR misses and non-100 maxima. | "Show it catching a fake." |
| **5** | **Pin the trust anchor.** Keep the certificate object in `load_uidai_public_key` (`aadhaar_qr.py:481-489`); check subject and validity window; expose SHA-256 fingerprint + subject + `notAfter` in `/health` (`main.py:567-574`); commit the expected fingerprint to the README. | 30min | Right now the entire cryptographic tier rests on an unauthenticated file path. This is the cheapest credibility win in the document. | "How do you know that certificate is UIDAI's?" |
| **6** | **Signed-PDF verification** with pyHanko (§2.5): e-Aadhaar (with password) and DigiLocker-issued PDFs. Check coverage level, chain, and modification level — not just "intact". | 1 day | A second genuine Tier-1 anchor; extends crypto verification to marksheets, which are otherwise permanently `UNVERIFIABLE`; fixes the HTTP 500 on PDF upload; and gives you a second detected-attack demo (incremental-update tamper that Chrome still shows as signed). | "How does this generalise beyond Aadhaar?" |
| **7** | **Fix the two face/binding bugs.** Move the frame-count guard above the liveness call (`main.py:243-247` → after `main.py:208`); add `Binding.CHECK_FAILED` so a failed match stops reporting as `NOT_ATTEMPTED` (`verdict.py:232-239`). | 30min | Removes a 500 and closes the "silently reads as not-checked" gap that favours an attacker. | — |
| **8** | **Privacy pass.** Extend `redacted()` (`aadhaar_qr.py:92-100`) to address/name/DOB; whitelist reason codes against `REASON_TEXT` before storing so exception strings stop entering the DB (`store.py:87`, `face_match.py:112`); add `RETENTION_DAYS` purge on startup; annotate `uidai_cert_path` (`config.py:11`). | 1.5h | Makes the §6 paragraph literally true instead of nearly true. Prevents a real teammate's home address on a projector. | "What do you store, and for how long?" |
| **9** | **Wire up `verify_contact_hash`** (`aadhaar_qr.py:440-459`, currently dead code) as an optional second binding: user types their mobile, you match it against the hash inside the signed payload. **[VERIFY]** the iteration rule first. | 2h | A second independent binding factor that a QR-transplanting forger cannot satisfy without also knowing the victim's registered mobile. ~90% already written. | "What if the face-match is fooled?" |
| **10** | **Server-issued liveness challenge nonce**: server picks the challenge and its order, client must satisfy it within a time window against a one-time token. | 3h | Currently the *client* picks the challenge (`main.py:496`) — the security property is inverted. Doesn't stop video replay, but stops the trivial "upload three prepared JPEGs" path. | "Can I just upload photos to your API?" |
| **11** | **Honesty pass on the README.** Fix `README.md:150-154` (the replay claim) after #1 lands; soften `README.md:125-127` from erasure guarantee to best-effort; state that `face_match.py:129-130` is inert. Add a "Known limitations" section listing screen replay, deepfake selfies, frame injection, PAN/marksheet ceiling, and ELA's inapplicability to camera photos. | 1h | A written limitations section is one of the highest-signal artefacts a hackathon team can produce, and you already have most of the content scattered in docstrings. Move it where a judge will read it. | **"What's your accuracy?"** — `README.md:156-162` already answers this well; make it findable. |

**Do not build:** a deepfake detector, a font-forensics module (`README.md:85-87` correctly
declines this), an AI-generated-image classifier, or any accuracy percentage you have not
measured on a labelled set. Each is an overclaim you cannot defend, and each costs time that
items 1–5 need.

**If you have one day, do 0, 1, 2, 3, 5.** That closes the replay hole, stops the system
accusing genuine documents, pins the trust anchor, and makes the README true. Those five are
the difference between a demo that survives Q&A and one that does not.

---

## Appendix — smaller findings

- `main.py:142` — `ok, reason = verhoeff.validate_aadhaar_number(...)`: `ok` is unused. More
  importantly, when OCR finds no number (`main.py:139-143`) **no reason code is emitted at
  all**, so the absence of a structural check is invisible in the output. Emit
  `AADHAAR_NUMBER_NOT_READ`.
- `ela.py:89` — `blocks` is bound from `_score_blocks` and never used.
- `ocr.py:337-346` (Pass 2) slides a 10-char window over *all* compacted OCR text and runs
  `_correct_pan_candidate` on each, which coerces arbitrary character runs into
  format-valid PANs. Combined with `_best_pan_candidate` (`ocr.py:397-407`) this can
  manufacture a plausible PAN from noise and report it (masked) as read from the card.
  Constrain Pass 2 to windows near a `PAN`/`Permanent Account Number` anchor, or require a
  minimum number of independent OCR passes to agree.
- `main.py:370` — the PDF branch keys on `document.content_type == "application/pdf"`.
  A PDF uploaded with a missing or wrong content type falls through to PIL and 500s. Sniff
  the `%PDF-` magic bytes instead.
- `aadhaar_qr.py:437` — an unrecognised contact flag silently falls back to `0`, corrupting
  the photo slice with no reason code. Emit one.
- `store.py:98` — `ORDER BY created_at DESC` on an ISO-8601 text column is correct
  lexicographically here (all UTC, `timespec="seconds"`), but it is fragile if the format
  ever changes. Fine for the demo; worth a comment.
- `main.py:44` — CORS allows `localhost:3000` and `localhost:8501` only. Correct for a demo;
  note that no endpoint has authentication (§3.5 item 4).
- `face_match.py:218-220` constructs a new `FaceMesh` per frame inside `_landmarks`. This is
  correct but slow — several hundred ms per frame of model setup. If liveness feels sluggish
  on stage, hoist the mesh out of the loop.
