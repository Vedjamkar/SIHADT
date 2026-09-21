# Document & Identity Check frontend

React + TypeScript + Vite interface for the FastAPI verification service.

From this directory:

```powershell
npm ci
npm run dev
```

Open `http://localhost:3000`. Start the API separately from the repository root:

```powershell
.venv/Scripts/python.exe -m uvicorn main:app --reload --port 8000
```

The API defaults to `http://localhost:8000`. Set `VITE_API_BASE_URL` to override it.
The backend must allow the frontend origin through its CORS configuration.

## Verification workspace

- Aadhaar checks the signed QR and printed document. Aadhaar + identity adds a live face comparison.
- Passport reads the photo-page MRZ, validates ICAO check digits, and reports expiry; it cannot authenticate the NFC chip.
- PAN and marksheets provide structural checks; a clean structure does not establish issuance.
- Face check compares a reference portrait with a camera sequence and a blink or head-turn prompt.
- The scan animation derives its preview from the uploaded image. It is a browser visualisation, not live server findings. The API returns one final response.
- Final noise, frequency, and compression maps come from the backend. These are advisory evidence, not an authenticity verdict.
- Deepfake and screen-replay detection are unavailable. A completed blink/head turn must not be presented as protection against those attacks.

Camera access requires a browser that supports `getUserMedia` and a secure context
(HTTPS or localhost). Camera streams stop after capture, on cancellation, and when
leaving the capture view. Frames stay in memory; the frontend does not persist them.
The subject must consent and be configured in the backend's `CONSENT_SUBJECTS` list.

## Validation

```powershell
npm run build
npm run lint
```

From the repository root:

```powershell
node --test tools/check_frontend_api.mjs
.venv/Scripts/python.exe tools/check_frontend_ui.py
```

The browser checks need the Vite server, Microsoft Edge, and `websocket-client`
from the Python environment. They use synthetic documents, a simulated camera,
and mocked API responses; no real biometric data or audit records are created.
Screenshots are written to the gitignored `demo_data/ui-review` directory.
Physical-camera testing and real-model accuracy evaluation remain separate checks.
