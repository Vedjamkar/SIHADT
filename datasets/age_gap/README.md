# Age-gap face-verification dataset

This directory defines an evaluation dataset, not a model-training dataset.
Biometric images are intentionally gitignored. Keep only manifests and
non-identifying provenance here.

Place lawful images under this layout:

```text
images/
  development/
    P001/
      age-18__id-photo.jpg
      age-24__current.jpg
    P002/
      age-20__id-photo.jpg
      age-29__current.jpg
  test/
    P101/
      age-19__id-photo.jpg
      age-31__current.jpg
    P102/
      age-22__id-photo.jpg
      age-35__current.jpg
```

Use pseudonymous subject IDs. A person must occur in only one split. The age is
the person's documented age when that image was captured; do not estimate it
from their face. Do not collect children's images for this demo. Historical
images of adults still require the subject's current consent.

Build a manifest:

```powershell
.\.venv\Scripts\python.exe tools\build_age_gap_manifest.py `
  datasets\age_gap\images datasets\age_gap\metadata.csv `
  --source consented-local `
  --rights-basis consent-register-v1
```

Validate it without loading the ML stack:

```powershell
.\.venv\Scripts\python.exe tools\evaluate_age_gap.py `
  datasets\age_gap\metadata.csv
```

Run the real production comparison path and write untracked reports:

```powershell
.\.venv\Scripts\python.exe tools\evaluate_age_gap.py `
  datasets\age_gap\metadata.csv --run --max-pairs-per-class 100
```

The manifest contains SHA-256 hashes so the evaluated image set can be shown to
be unchanged without exposing any image. It must not contain names, Aadhaar
numbers, addresses, or other direct identifiers.
