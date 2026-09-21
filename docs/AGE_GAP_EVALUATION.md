# Cross-age face verification: what we built and what we did not train

## The defensible claim

> VerifAI did not train a foundation face model. It integrates pretrained
> RetinaFace and ArcFace through DeepFace, then evaluates the resulting identity
> distance on a separately held-out, provenance-tracked age-gap dataset. Our own
> work is the document-to-person evidence flow, privacy controls, liveness
> geometry, pair construction, threshold evaluation, and verdict policy.

Do not say that VerifAI learned how humans grow. The current system has no age
estimator or age-progression generator. It asks a narrower question: **does the
identity representation remain close enough when the two photographs were
taken several years apart?**

## How a changed face is checked

1. RetinaFace detects and aligns the face in each image.
2. ArcFace converts each aligned face into a 512-value identity embedding.
3. DeepFace calculates cosine distance between the two embeddings.
4. The production rule accepts a pair when distance is at most `0.68`.
5. Age can change hair, skin, face shape, weight, and image quality, so a true
   pair may move farther apart. That is why we measure false-reject rate by
   elapsed-age bucket instead of claiming age invariance from the model name.

The ArcFace paper describes training with an additive angular-margin loss to
make images of the same identity compact and different identities separated in
embedding space. The paper reports experiments on AgeDB-30, but that published
result is not VerifAI's result. The exact DeepFace-distributed H5 weight file is
third-party pretrained material; until its training-data lineage is verified,
cite the paper as architectural provenance, not as proof of the local file's
training set.

## Dataset and evaluation protocol

Use `datasets/age_gap/` and the two scripts in `tools/`:

- `build_age_gap_manifest.py` records a pseudonymous identity, documented age
  at capture, split, source, rights basis, and image hash.
- `evaluate_age_gap.py` rejects identity leakage between development and test,
  builds same-person and different-person pairs, and runs the exact
  `face_match.compare_faces` production path.
- Development identities may be used to choose a candidate threshold. Test
  identities remain untouched until final evaluation.
- Report false-accept rate (different people accepted), false-reject rate (same
  person rejected), comparison completion, and same-person false rejects for
  `0-5`, `6-10`, `11-20`, and `21+` year gaps.
- Report synthetic and real/consented results separately. Synthetic ageing is
  useful for a UI demonstration, but it is not evidence of performance on real
  human ageing.

Minimum useful pilot: at least 20 development identities and 20 disjoint test
identities, with two or more ages per identity and balanced capture conditions.
That is still a pilot, not a population-level accuracy claim. A stronger study
needs more people, devices, lighting conditions, age bands, and demographic
coverage, plus confidence intervals and independent review.

## Exact model path through this repository

```text
frontend/src/components/verify/FaceCapture.tsx
  captures 20 in-memory frames over about 3 seconds
        |
frontend/src/api/client.ts
  POST /verify/face or /verify/aadhaar-full
        |
main.py
  validates consent/uploads; selects the middle live frame
  Aadhaar-full prefers the photo inside the signed QR payload
        |
face_match.py:check_liveness
  MediaPipe landmarks -> blink EAR or normalised nose movement
        |
face_match.py:compare_faces
  DeepFace.verify(model=ArcFace, detector=retinaface, metric=cosine)
        |
verdict.py
  keeps document authenticity and identity binding as separate outcomes
```

Important source locations:

- `face_match.py:42-49` selects ArcFace, RetinaFace, cosine threshold `0.68`,
  and the hand-set liveness thresholds.
- `face_match.py:75-105` performs the face comparison.
- `face_match.py:142-212` performs blink/head-turn checks.
- `face_match.py:239-281` obtains MediaPipe landmarks and derives eye/yaw
  geometry.
- `main.py:445-582` binds Aadhaar's signed QR photo to a live presenter.
- `main.py:886-899` implements standalone face verification.
- `frontend/src/components/verify/FaceCapture.tsx:12-13` defines capture count
  and interval; lines 99-119 keep frames in memory.

## What to show judges

Show three artefacts together:

1. `metadata.csv` with pseudonymous IDs, ages, provenance and hashes.
2. `pair_results.csv` with each pair's age gap, distance and decision.
3. `report.json` with the fixed-threshold and held-out test FAR/FRR, plus model
   versions and local weight-file hashes.

Use this sentence:

> We evaluated a pretrained identity model across documented age gaps. We did
> not teach a model human growth, and we do not infer age. Here are our held-out
> false-accept and false-reject results, the exact dataset provenance, and the
> hashes of the weights and images used.

Until `report.json` exists from a lawful dataset, describe this as the
**implemented evaluation protocol**, not as completed validation.

## Primary references

- [ArcFace, CVPR 2019](https://openaccess.thecvf.com/content_CVPR_2019/html/Deng_ArcFace_Additive_Angular_Margin_Loss_for_Deep_Face_Recognition_CVPR_2019_paper.html)
- [RetinaFace, CVPR 2020](https://openaccess.thecvf.com/content_CVPR_2020/html/Deng_RetinaFace_Single-Shot_Multi-Level_Face_Localisation_in_the_Wild_CVPR_2020_paper.html)
- [MediaPipe Face Mesh, CVPRW 2019](https://research.google/pubs/real-time-facial-surface-geometry-from-monocular-video-on-mobile-gpus/)
- [NIST face-recognition demographic effects](https://pages.nist.gov/frvt/html/frvt_demographics.html)
