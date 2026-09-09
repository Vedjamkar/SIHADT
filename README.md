# Document & Identity Verification

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![React](https://img.shields.io/badge/frontend-React-61dafb)
![Tests](https://img.shields.io/badge/tests-17%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

FastAPI backend that checks whether a government or institutional document (Aadhaar, PAN,
marksheet) is internally consistent and — for Aadhaar — whether its QR payload carries a valid
UIDAI signature. Local/demo scope, not production.

**It does not query any government database and is not official verification.** That sentence
ships inside every API response and should never be dropped from the UI.

---

### Contents

- [Status](#status-running-with-the-core-defences-verified)
- [Start here](#start-here)
- [Endpoints](#endpoints)
- [How each check works](#how-each-check-works)
- [The verdict engine](#the-verdict-engine)
- [Privacy constraints](#privacy-constraints-enforced-in-code-rather-than-policy)
- [Judge questions](#judge-questions)
- [Repository layout](#repository-layout)
- [Tests](#tests)

---

> ## Status: running, with the core defences verified
>
> This code was AI-generated from the team's plan document and, until 2026-09-08, **had never
> been executed** — it could not even be imported. Since then the app boots, and the
> cryptographic and identity-binding paths have been verified by running them, not by reading
> them.
>
> **Verified working:** Aadhaar Secure QR signature verification, the QR-replay defence,
> the tiered verdict engine, the marksheet total check, Verhoeff, and redaction.
> **Frontend:** a React verification workspace, animated image-derived scan preview,
> forensic map viewer, guided camera capture, and searchable history are available in `frontend/`.
> **Still unverified or absent:** ELA accuracy against real splices and deepfake/presentation-attack
> detection. Browser flow tests use synthetic inputs; physical-camera accuracy is a separate check.
>
> Anything still marked **[NOT IMPLEMENTED]** below is genuinely absent. Do not claim it.
> Current status and the ordered task list live in
> [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).

---

## Start here

| You want to… | Read |
|---|---|
| Get it running on your machine | [`docs/SETUP.md`](docs/SETUP.md) |
| Know what actually works, and the ordered task list | [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) |
| Brief the team — state, the replay attack, direction | [`docs/briefing.html`](docs/briefing.html) |
| Understand the project, decisions, and open questions | [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) |
| Know the security holes and the legal position | [`docs/ADVISORY_OPUS.md`](docs/ADVISORY_OPUS.md) |
| See the file-by-file code audit | [`docs/CODE_AUDIT_SONNET.md`](docs/CODE_AUDIT_SONNET.md) |

Quick start, in full detail in `docs/SETUP.md`:

```bash
py -V:3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000/docs to exercise every endpoint without a frontend.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/verify/aadhaar` | QR decode, UIDAI signature verify, Verhoeff, ELA |
| POST | `/verify/aadhaar-full` | The above plus face-match against the **signed** QR photo |
| POST | `/verify/pan` | OCR, structural validation, ELA |
| POST | `/verify/marksheet` | OCR, range checks, ELA, and the arithmetic total check |
| POST | `/verify/face` | Standalone ID photo vs live frames |
| GET | `/dashboard/history` | Recent checks with reasons |
| GET | `/dashboard/summary` | Verdict counts, per-day trend, top reason codes |
| GET | `/reasons` | Full reason-code dictionary for the UI to render |
| GET | `/health` | Cert loaded, consent enforcement state |

The frontend runs at `http://localhost:3000` (`cd frontend`, `npm ci`, `npm run dev`).
See [`frontend/README.md`](frontend/README.md) for camera requirements and frontend tests.
`/docs` remains available for direct API inspection.

---

## How each check works

**Aadhaar Secure QR (V2).** The payload is a long decimal string. Convert to a big integer,
then to bytes, gunzip, and you get 0xFF-delimited text fields, a JPEG2000 photo, optional
SHA-256 contact hashes, and a trailing 256-byte RSA signature. That signature is SHA256-with-RSA
over every preceding byte, made with UIDAI's private key. Verify it against UIDAI's public
certificate and you have proved the field values are issuer-signed and bit-for-bit unaltered.

Two real implementation traps, both handled in `aadhaar_qr.py`:

1. Do not `data.split(b"\xff")`. The embedded photo is binary and its JPEG markers contain
   0xFF, so a naive split shreds the image and shifts every later offset. Scan for exactly the
   16 delimiters you need and stop.
2. You cannot find where the photo ends by scanning forward — its length is not declared. Count
   backwards from the signature: subtract 256 for the signature, then 32 bytes per contact hash
   indicated by field 0.

**What a valid signature does and does not prove.** It proves *these exact QR bytes* came from
UIDAI unaltered. It says nothing about the piece of paper around them — the printed photo, name,
and number are unsigned and can be anything. This distinction is the whole ballgame; see
"Can't a forger copy a real QR?" below.

**Legacy V1 QR** is plain XML with no signature. Anyone can type it into a text editor and
generate a QR. The code returns `QR_V1_LEGACY_UNSIGNED` and the verdict engine refuses to call
it genuine. If the app ever shows a green tick for a V1 QR, it is lying.

**Verhoeff checksum.** Dihedral-group-D5 check digit over the first 11 digits. Catches every
single-digit error and every adjacent transposition. Pure arithmetic on the number, so a forger
generates a valid one in a `for` loop. A pass means "not obviously garbage", never "real".
*This module is verified working — it is the one piece tested by execution.*

**PAN.** Format only: five letters, four digits, one letter, with the fourth character encoding
holder type. There is no public check digit and no offline cryptographic material. The only
authoritative check is the Income Tax Department's own API.

**ELA.** Re-encode at quality 90, diff against the original, flag blocks whose mean error is
above the image's own distribution.

> **Partly fixed, and still the weakest signal here.** The old thresholds
> (`FLAG_SIGMA=2.5`, `MIN_FLAGGED_FRACTION=0.004`) put the firing point *below* the expected
> null rate of ~0.62%, so the anomaly flag fired on nearly every JPEG. Now 3.0 sigma firing at
> 2%, an order of magnitude clear of chance. ELA also now reports `applicable=False` for images
> straight from a camera, which have a single compression history and nothing to compare —
> the common case here, since photographing a printout is how documents reach us.
>
> **Not yet validated:** the new thresholds are justified arithmetically but have *not* been
> shown to still catch a real splice. Synthetic test images do not exercise ELA. Validating this
> needs a real photograph of a real printed document with a real edit. Until someone does that,
> do not claim ELA works.

**Marksheet.** Range checks, baseline scanning, and the arithmetic consistency check: subject
marks are summed and compared against the total and percentage printed on the sheet. This is the
only marksheet check that is deterministic rather than heuristic — the marks either add up or
they do not, and arithmetic does not care about scan quality. It is also the commonest crude
forgery: a subject mark raised while the printed total is left alone, or the total inflated
while the rows beneath it stay put.

Verified: a genuine sheet (computed 457 = printed 457) yields `TOTAL_CONSISTENT`; the same sheet
with the total altered to 487 yields `TOTAL_MISMATCH` and `PERCENTAGE_MISMATCH`, giving
`STRUCTURALLY_INVALID`.

*Limitation:* the row parser assumes the CBSE layout, where a row's last three numbers are
theory, internal and obtained total. A sheet printing an explicit "maximum marks" column will
have that maximum read as the obtained mark.

Font forensics from the plan was deliberately **not** implemented, and that call was correct:
glyph metrics are not recoverable from Tesseract output, and per-character height variance
tracks scan skew far more than tampering.

**Face-match and liveness.** ArcFace embeddings, cosine distance, threshold 0.68 (DeepFace's
tuned default for that model — do not reuse a threshold across models). Liveness compares
MediaPipe landmark geometry across a burst of frames: eye-aspect-ratio dip for blink,
normalised nose offset for head turn. Note that a landmark blink check is defeated by playing a
video on a phone screen; passive presentation-attack detection is a known gap.

---

## The verdict engine

Averaging or weighting checks is wrong in both directions: a genuine document photographed
badly picks up ELA noise despite carrying a cryptographic proof of issuance, and a forgery with
a clean compression history gains points it never earned. A proof and a heuristic do not belong
in the same arithmetic. So checks are tiered and the strongest available tier decides.

| Tier | Checks | Weight in verdict |
|---|---|---|
| 1 Cryptographic | UIDAI QR signature | Decides outright |
| 2 Structural | Verhoeff, PAN pattern, marksheet arithmetic | A failure is a hard flag. A pass means little. |
| 3 Heuristic | ELA, baseline alignment | Advisory only. Never the sole cause of a flag. |

Six verdicts, and none of them is the word "verified":

- `GENUINE_SIGNED` — Tier 1 passed. Issuer-signed, unaltered.
- `FORGED_SIGNATURE` — Tier 1 failed. The strongest possible claim.
- `SIGNED_BUT_ALTERED` — the signature is genuine, and the printed card contradicts it. A
  transplanted QR. Ranked above `GENUINE_SIGNED`, because this is the one case where
  "issuer-signed" is true and dangerously misleading at the same time.
- `STRUCTURALLY_INVALID` — Tier 2 failed. Explainable and document-specific.
- `UNVERIFIABLE` — no Tier 1 available, Tier 2 clean. **The honest outcome for every PAN and
  every marksheet. It is not a pass.**
- `NEEDS_REVIEW` — Tier 3 raised something on an otherwise clean document.

`identity_binding` is reported **separately** from the verdict, on its own axis: `BOUND`,
`NOT_BOUND`, `LIVENESS_FAILED`, `CHECK_FAILED`, `NOT_ATTEMPTED`. `CHECK_FAILED` means an
attempted face/liveness check could not produce a result. `BOUND` requires both checks to pass.
Keep them separate in the UI. A genuine
Aadhaar held by the wrong person is `GENUINE_SIGNED` + `NOT_BOUND`, and collapsing those into
one badge is precisely how the "can't a forger copy a real QR?" question sinks a demo.

Both of the engine's original defects are fixed. Structural failures are now evaluated *before*
a cryptographic pass, so a printed number failing Verhoeff is no longer suppressed under
"issuer-signed and unaltered" — the signature covers the QR payload, not the printed card. And
the Tier 3 rule is now enforced rather than merely stated: a single heuristic signal is advisory
and cannot move the verdict, and it takes two independent ones to ask for a human.

Verified: one ELA flag alone → `UNVERIFIABLE` with the flag demoted to advisory; two heuristic
flags → `NEEDS_REVIEW`; a valid signature plus a failed checksum → `STRUCTURALLY_INVALID`.

---

## Privacy constraints, enforced in code rather than policy

- **Biometrics.** Frames live in local variables, temp files are zero-filled and `fsync`ed
  before unlink in a `finally` block, and no embedding or crop reaches the response or the
  database. *(Claimed in code; not yet verified by running it.)*
- **Audit schema.** `store.py` has no image column, no embedding column, no full identifier
  column. A column you never populate eventually gets populated by someone at 3am. A column
  that does not exist does not.
- **Consent.** `/verify/face` and `/verify/aadhaar-full` return 403 unless `consent_subject` is
  in `CONSENT_SUBJECTS`. The whiteboard rule "only consenting teammates" survives contact with
  a 2am test session this way and not otherwise.
- **Redaction.** `reference_id` is masked, and so are name, date of birth and every address
  field — each reduced to a first character plus asterisks, enough to sanity-check that OCR and
  the signed payload describe the same record, not enough to identify anyone from a screenshot.
  State and pincode are kept, being too coarse to identify on their own. Verification never
  needed to display who someone is: the verdict, the reason codes and the signature result carry
  the whole finding.
- **Disclaimer** ships inside every response body, so the frontend has to actively discard it
  to mislead someone.

---

## Judge questions

**"Is this real verification or just format checking?"** Both, and the app says which. Aadhaar
is real cryptographic verification against UIDAI's signature. PAN and marksheets are consistency
checking only, and they return `UNVERIFIABLE`, never a pass. Naming that boundary yourself is
worth more than any demo polish.

**"Can't a forger just copy real numbers or QR codes?"** Yes — and this is the attack that
matters. A forger can print their *own* photo on the front of a card and a *stranger's genuine*
Secure QR on the back. The signature verifies, because the QR really is issued by UIDAI.

The defence is to use the photo *inside the signed payload* rather than the one printed on the
card, and to cross-check the printed name and number against the signed fields. **The system
does this, and it is verified end to end:**

| Specimen | Signature | Signed photo vs printed photo | Verdict |
|---|---|---|---|
| genuine | valid | match, distance 0.0654 | `GENUINE_SIGNED` |
| replay | valid — the QR really is signed | mismatch, distance 0.7024 | `SIGNED_BUT_ALTERED` |

`SIGNED_BUT_ALTERED` is a sixth verdict added for exactly this case. Calling a transplanted QR
`FORGED_SIGNATURE` would be false — the signature is genuine — and calling it `GENUINE_SIGNED`
would be dangerous. The card is real; the paper around it is not the paper it was issued for.

Generate the specimens yourself with `tools/mock_pki.py replay`.

> **Caveat before you lean on this on stage:** the face distances sit close to the 0.68
> threshold (0.6889 in isolation, 0.7024 through the pipeline). Try several face pairs first.
> If margins stay this tight, the threshold needs review rather than trust.

**"What's your accuracy, and on what data?"** Signature verification is not statistical, so
accuracy is the wrong frame: it is a cryptographic check that passes or fails. Face-match uses
ArcFace's published benchmarks, not ours. ELA we have not measured on a labelled dataset, so it
ships as a reviewer aid and not a classifier. That answer is stronger than an invented
percentage, and an invented percentage is the thing most likely to get you taken apart in Q&A.
If you want a real number, MIDV-2020 and DocTamper are public datasets you can measure against.

**"Do you have legal permission to process Aadhaar data?"** Offline QR verification against
UIDAI's published certificate is the intended offline path and needs no database access. Be
precise: you are not a registered AUA/KUA, you query nothing, you store no identifiers, and
demo data came from teammates asked directly. A fuller treatment, with the specific statutes,
is in `docs/ADVISORY_OPUS.md` — verify its legal citations before quoting them.

**"How does this scale beyond a demo?"** Signature verification is a few milliseconds of RSA
and scales trivially. The real costs are face-match compute and, for genuine PAN or board
verification, per-call API fees plus registration you do not currently have. The credible
production path is issuer-side signing (what DigiLocker already is) rather than better forensics.

---

## Repository layout

Flat, single package. Run as `uvicorn main:app`.

```
main.py         FastAPI app, all endpoints, response envelope
config.py       Settings, consent list, cert path (env-overridable)
aadhaar_qr.py   Secure QR decode + UIDAI RSA signature verification
verhoeff.py     Aadhaar check-digit validation  [verified working]
pan.py          PAN structural validation
marksheet.py    Marksheet checks
ocr.py          Tesseract wrapper
ela.py          Error Level Analysis
face_match.py   ArcFace match + MediaPipe liveness
verdict.py      Tiered verdict engine + reason-code catalogue
store.py        SQLite audit history
docs/           Setup, ship plan, project state, audits
```

## Tests

```bash
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

17 tests, under a second, stdlib only — no pytest needed. They pin the behaviours that matter:
Verhoeff catching every single-digit error and adjacent transposition, every rung of the verdict
ladder (including that a transplanted QR outranks a valid signature, and that no verdict is ever
the word "verified"), the marksheet arithmetic check, and the ELA threshold's relationship to
its own null rate.

Face matching is deliberately **not** in this suite — it needs ~260 MB of model weights and
minutes on a cold cache, which would make it something nobody runs. Use
`tools/check_face_pipeline.py` for that, separately.

*(An earlier version of this README told you to run `python tests/test_core.py` before demo day
when that file did not exist. It does now.)*
