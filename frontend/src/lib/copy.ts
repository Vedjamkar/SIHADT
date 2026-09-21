/**
 * Centralised human-readable copy for verdicts and bindings.
 *
 * Rules this file exists to enforce (see project brief):
 *  - never the word "verified" as a claim of authenticity
 *  - never accusatory language ("fake", "fraud", "rejected")
 *  - UNVERIFIABLE reads as neutral, not as a failure
 *  - verdict and identity_binding are described independently
 */
import type { DocumentKind, IdentityBinding, ReasonTier, Verdict } from "../types/api";

export interface VerdictCopy {
  /** Semantic class suffix, e.g. "genuine" -> "verdict-card--genuine". */
  tone: string;
  title: string;
  description: string;
}

export const VERDICT_COPY: Record<Verdict, VerdictCopy> = {
  GENUINE_SIGNED: {
    tone: "genuine-signed",
    title: "Issuer-signed and unaltered",
    description:
      "The data inside this document's QR code carries a valid UIDAI signature and has not changed since it was issued. This is a claim about the document's data, not about the person presenting it — see the identity binding below.",
  },
  FORGED_SIGNATURE: {
    tone: "forged-signature",
    title: "Signature check failed",
    description:
      "The QR payload's digital signature did not validate. That means the data was altered after issuance, or the code was not produced by UIDAI. This is the strongest finding this tool can make, and it is worth a closer, human look rather than an automatic conclusion.",
  },
  SIGNED_BUT_ALTERED: {
    tone: "signed-but-altered",
    title: "Genuine QR on a card that contradicts it",
    description:
      "The signature itself is valid, but what's printed on the card disagrees with the signed data — for example the number, name, or photo. A likely explanation is that a genuine QR code was moved onto different paper. Treat this as needing a closer look, not as a confirmed conclusion.",
  },
  STRUCTURALLY_INVALID: {
    tone: "structurally-invalid",
    title: "Structurally invalid",
    description:
      "Something in the document's own numbers or fields does not add up — a checksum, a total, or a pattern that should hold regardless of any signature. This is explainable and specific to this document; see the reasons below for exactly what failed.",
  },
  UNVERIFIABLE: {
    tone: "unverifiable",
    title: "Not independently verifiable",
    description:
      "There is no cryptographic signature to check for this document type, and nothing in its structure raised a concern. This is the expected, honest result for this kind of document — it is not a failure and not a mark against the person who submitted it.",
  },
  NEEDS_REVIEW: {
    tone: "needs-review",
    title: "Needs human review",
    description:
      "A couple of low-confidence signals were raised together. Individually, signals like this are common with ordinary scans and print quality — that's why it takes more than one to reach this outcome. It means a person should look, not that something is wrong.",
  },
};

export interface BindingCopy {
  tone: string;
  title: string;
  description: string;
}

export const BINDING_COPY: Record<IdentityBinding, BindingCopy> = {
  BOUND: {
    tone: "bound",
    title: "Live face matched",
    description:
      "The live selfie matched the photo associated with this document, and the liveness challenge was satisfied.",
  },
  NOT_BOUND: {
    tone: "not-bound",
    title: "Live face did not match",
    description:
      "The live selfie did not match the photo associated with this document. Poor lighting, angle, or image quality can cause this on a genuine match — it is worth a retake before drawing a conclusion.",
  },
  LIVENESS_FAILED: {
    tone: "liveness-failed",
    title: "Liveness check not satisfied",
    description:
      "The requested liveness challenge was not completed across the frames provided, so identity could not be confirmed from this attempt. This check is not designed to catch video or screen replay.",
  },
  CHECK_FAILED: {
    tone: "check-failed",
    title: "Identity check inconclusive",
    description:
      "The face or liveness analysis could not produce a usable comparison. This attempt did run, but image quality, face detection, or the analysis service prevented a conclusion. Retake in even light with one face centred in frame.",
  },
  NOT_ATTEMPTED: {
    tone: "not-attempted",
    title: "Not checked against a person",
    description:
      "No live selfie was supplied with this document, so it was never compared against a person. Document authenticity and identity binding are evaluated separately.",
  },
};

export const TIER_LABEL: Record<ReasonTier, string> = {
  cryptographic: "Cryptographic",
  structural: "Structural",
  heuristic: "Heuristic (advisory)",
};

export const TIER_ORDER: ReasonTier[] = ["cryptographic", "structural", "heuristic"];

export const DOC_TYPE_LABEL: Record<string, string> = {
  aadhaar: "Aadhaar",
  pan: "PAN",
  passport: "Passport",
  marksheet: "Marksheet",
  face: "Face check",
};

/**
 * What each document kind can and cannot prove, shown BEFORE upload so the
 * ceiling on the outcome is never a surprise. PAN and marksheet have no
 * cryptographic material at all — the honest best case is UNVERIFIABLE, and
 * the picker screen says so up front rather than letting someone discover
 * it only after waiting on a result.
 */
export interface DocKindInfo {
  label: string;
  tagline: string;
  description: string;
  /** "cryptographic" can reach GENUINE_SIGNED/FORGED_SIGNATURE; "structural" tops out at UNVERIFIABLE. */
  ceiling: "cryptographic" | "structural";
  ceilingNote: string;
  fields: string;
}

export const DOC_KIND_INFO: Record<DocumentKind, DocKindInfo> = {
  aadhaar: {
    label: "Aadhaar",
    tagline: "Signature check on the QR code",
    description:
      "Reads the QR code on the back and checks UIDAI's digital signature against what's printed on the front.",
    ceiling: "cryptographic",
    ceilingNote:
      "Cryptographic evidence is possible here — this can reach a genuine-signed or forged-signature finding.",
    fields: "Front image, and ideally the back (QR side).",
  },
  "aadhaar-full": {
    label: "Aadhaar + identity check",
    tagline: "Adds a live selfie comparison",
    description:
      "Everything the Aadhaar check does, plus a liveness challenge and a face comparison against the document photo — a separate finding from the document check.",
    ceiling: "cryptographic",
    ceilingNote:
      "Cryptographic evidence is possible for the document; identity binding is reported separately from it.",
    fields: "Front and back images, a guided live camera sequence, and consent.",
  },
  pan: {
    label: "PAN",
    tagline: "Structural checks only",
    description:
      "No cryptographic signature exists on a PAN card for this tool to check — only field structure and formatting.",
    ceiling: "structural",
    ceilingNote:
      "There is no signed data to check on a PAN. The best possible outcome here is UNVERIFIABLE — that's expected, not a shortfall.",
    fields: "One image of the card.",
  },
  passport: {
    label: "Passport",
    tagline: "MRZ checksum and expiry checks",
    description:
      "Reads the machine-readable zone on the photo page and checks the passport number, birth date, expiry date, and composite check digits.",
    ceiling: "structural",
    ceilingNote:
      "MRZ check digits prove internal consistency, not issuer authenticity. Chip verification requires an NFC passport reader.",
    fields: "One clear image or PDF of the complete photo page, including both MRZ lines.",
  },
  marksheet: {
    label: "Marksheet",
    tagline: "Arithmetic and structural checks",
    description:
      "Checks that subject totals and formatting are internally consistent. Nothing here is cryptographically signed.",
    ceiling: "structural",
    ceilingNote:
      "There is no signed data to check on a marksheet. The best possible outcome here is UNVERIFIABLE — that's expected, not a shortfall.",
    fields: "One image, and the five subject names to total.",
  },
  face: {
    label: "Face + liveness",
    tagline: "Live challenge against an ID portrait",
    description:
      "Captures a short, consented camera sequence and compares it with a supplied ID portrait. No frames are retained by this browser.",
    ceiling: "structural",
    ceilingNote:
      "This is an identity-binding check, not a document-authenticity finding. Deepfake and screen-replay detection are not available.",
    fields: "One ID portrait, a live camera sequence, and explicit consent.",
  },
};

/**
 * The steps shown while a check is running, so the wait reads as "the
 * system doing something specific" rather than a bare spinner. Order
 * matches roughly what the backend actually does for that document kind.
 */
export const CHECKING_STEPS: Record<DocumentKind, string[]> = {
  aadhaar: [
    "Reading the QR code",
    "Verifying the UIDAI signature",
    "Comparing signed data to the printed card",
  ],
  "aadhaar-full": [
    "Reading the QR code",
    "Verifying the UIDAI signature",
    "Comparing signed data to the printed card",
    "Checking liveness across the selfie frames",
    "Comparing the live face to the document photo",
  ],
  pan: ["Reading the document fields", "Checking structural consistency"],
  passport: [
    "Locating the machine-readable zone",
    "Reading passport fields",
    "Checking ICAO check digits and expiry",
  ],
  marksheet: [
    "Reading the marksheet fields",
    "Verifying subject totals and formatting",
  ],
  face: [
    "Receiving the consented camera sequence",
    "Measuring the liveness gesture",
    "Comparing facial features",
  ],
};
