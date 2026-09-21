# Other identity documents

Reviewed 2026-09-09 against the current implementation and official references.

| Document | Current support | Next useful work | What a pass means |
| --- | --- | --- | --- |
| Passport | UI and `/verify/passport` accept an image/PDF data page, run MRZ-focused OCR, validate TD3/TD1 check digits, and report expiry | Test broader issuer specimens and camera conditions; NFC chip reading remains separate | Internal consistency only; a photo cannot authenticate the chip |
| Driving licence / vehicle RC | No dedicated implementation | Prefer issuer-delivered DigiLocker records, validate signatures/trust chain, and implement consent-based requester integration | Depends on verified issuer provenance, not a plausible licence number |
| Other national IDs with MRZ | Existing TD1 parser is a starting point | Confirm supported country/document layout before reusing it; add specimen tests and explicit unknown formats | MRZ checksums are public arithmetic, not issuer proof |
| Voter ID and other printed cards | No dedicated implementation | Research issuer-specific verification access before adding UI claims | OCR/format checking alone cannot establish validity |

Passport image scanning is available in the document picker. Authenticating an electronic
passport would be separate work: an NFC reader, chip access protocols,
signed data groups, passive authentication and a trusted certificate chain. The current
browser image workflow cannot provide that evidence.

DigiLocker distinguishes documents received from issuers from user-uploaded files. Its
FAQ describes consent-based exchange between issuers and requesters and signature/QR
verification of issued DL/RC documents. Do not label an uploaded PDF authentic merely
because its filename mentions DigiLocker. Requester registration/integration is needed;
the public Parivahan licence-details page is not evidence of unrestricted API access.

References:

- [ICAO Doc 9303 Part 11: security mechanisms](https://www.icao.int/publications/Documents/9303_p11_cons_en.pdf)
- [DigiLocker FAQ: issued documents and verification](https://www.digilocker.gov.in/web/about/faq)
- [DigiLocker verification portal](https://verify.digilocker.gov.in/)
- [Parivahan licence and registration details](https://parivahan.gov.in/parivahan//en/content/license-registration-details)

Real-document testing must remain separate from synthetic fixture results. Use only
consented files, keep image/identity fields out of test output, and avoid saving biometric
data or real documents as fixtures.
