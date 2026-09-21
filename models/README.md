# models/

Pretrained model files for the face pipeline. **Nothing here is tracked by git** except
this file — the weights total ~800 MB and two of them exceed GitHub's 100 MB per-file
limit.

Fill the directory with:

```bash
./.venv/Scripts/python.exe tools/fetch_models.py
```

That downloads each file from its upstream release, checks the SHA-256 and byte size
pinned in `face_match.REQUIRED_MODELS`, and writes it into place atomically. Re-running
is a no-op once everything is present; `--check` reports without downloading and
`--verify` re-hashes what is on disk.

The launcher (`Launch VERIFai.cmd` / `tools/launch.ps1`) runs this step automatically,
and `GET /health` reports `face_models_ready` / `face_models_missing`.

| File | Used by | Source |
|---|---|---|
| `.deepface/weights/arcface_weights.h5` | face match (ArcFace embedding) | serengil/deepface_models v1.0 |
| `.deepface/weights/retinaface.h5` | face detection (RetinaFace) | serengil/deepface_models v1.0 |
| `.deepface/weights/age_model_weights.h5` | age-gap advisory | serengil/deepface_models v1.0 |
| `face_landmarker.task` | liveness (MediaPipe Face Landmarker) | storage.googleapis.com/mediapipe-models |

The `.deepface/weights/` nesting is what DeepFace and the RetinaFace package hard-code
under `$DEEPFACE_HOME`; `config.py` sets `DEEPFACE_HOME` to this directory before
anything imports DeepFace. Set `DEEPFACE_HOME` yourself to keep the files elsewhere
(for example a shared drive on a machine with several clones).

If a file is missing, the face-match, age-gap, and liveness checks fail fast with
`run tools/fetch_models.py` in the error detail rather than downloading inside the
request.
