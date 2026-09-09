Document & Identity Verification App
Hackathon Project Plan — Team Reference Document
1. What We're Building
A document and identity verification app. A user uploads a government or institutional document (Aadhaar,
PAN, or marksheet) and the app returns a verified/flagged verdict with clear reasons. It also includes a
biometric face-match feature: a live selfie is compared against the photo on the uploaded ID to confirm the
document belongs to the person presenting it.
2. Core Features
Feature
What It Does
Depth
Aadhaar QR verify
Decodes the QR code and checks UIDAI's digital signature
Deep — showpiece
Verhoeff checksum
Validates the Aadhaar number mathematically
Quick add-on
PAN format check
Validates structure (letter/digit pattern)
Light
ELA tamper detection
Flags edited/photoshopped regions on any document
Medium — all 3 docs
Marksheet checks
Layout/font consistency, field validation
Light
Biometric face-match
Live selfie vs ID photo, similarity score, liveness check
Medium — showpiece
Dashboard
Flagged vs verified docs, reasons shown, trends
UI layer
3. Non-Negotiable Constraints
●
Face-match: compare live, discard immediately — never store biometric data.
●
Demo data: only consenting teammates — ask each person directly before using their ID/selfie.
●
Blur real ID numbers on screen if a real document is shown during the demo.
●
No claim of official government verification — this is a "does it look genuine" tool, not a live database
check.
4. Tech Stack
●
Backend: Python + FastAPI
●
OCR: Tesseract / EasyOCR
●
QR decoding: pyzbar
●
Face-match: DeepFace or face_recognition
●
Image forensics (tamper detection): OpenCV — Error Level Analysis (ELA)
●
Frontend: Streamlit or simple React
●
Scope: working local/demo app, not production infrastructure
5. Live Demo Script

●
1. Upload a genuine Aadhaar → QR signature verifies → shown as genuine.
●
2. Upload an edited Aadhaar (name/DOB changed) → QR fails and ELA highlights the edited region →
shown as flagged.
●
3. Live selfie vs ID photo → match/no-match score, with a liveness check (e.g. blink or head turn).
●
4. Show the dashboard with flagged vs verified history and reasons for each flag.
6. Suggested Task Split
Role
Owns
Person A
Aadhaar QR verification + Verhoeff checksum
Person B
ELA tamper detection (all document types)
Person C
Biometric face-match + liveness check
Person D
Frontend + dashboard
Team Lead (you)
Pitch, demo prep, judge Q&A prep, teammate consent for demo data
7. Questions Judges Will Likely Ask
●
What makes this different from other fraud-detection projects?
●
Do you have legal permission to process Aadhar data?
●
Can't a forger just copy real numbers/QR codes? How do you catch that?
●
Show it catching a fake marksheet — live.
●
What's your accuracy, and on what data did you test it?
●
Is this real verification or just format checking?
●
How does this scale beyond a demo — real API access, real cost?
Priority if time runs short: QR verification > Verhoeff checksum > ELA tamper detection > face-match > dashboard
polish.

