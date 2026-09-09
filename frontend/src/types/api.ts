/**
 * TypeScript types for the verification API's response envelope.
 *
 * `verdict` and `identity_binding` are deliberately separate fields (see
 * verdict.py in the backend) — a document can be GENUINE_SIGNED while the
 * person holding it is NOT_BOUND. Never merge these into a single flag.
 */

export type Verdict =
  | "GENUINE_SIGNED"
  | "FORGED_SIGNATURE"
  | "SIGNED_BUT_ALTERED"
  | "STRUCTURALLY_INVALID"
  | "UNVERIFIABLE"
  | "NEEDS_REVIEW";

export type IdentityBinding =
  | "BOUND"
  | "NOT_BOUND"
  | "LIVENESS_FAILED"
  | "CHECK_FAILED"
  | "NOT_ATTEMPTED";

export type ReasonTier = "cryptographic" | "structural" | "heuristic";

export interface ReasonItem {
  code: string;
  tier: ReasonTier;
  message: string;
}

/**
 * `details` varies per document type (aadhaar/pan/marksheet/face all report
 * different fields), so it is intentionally a loose record rather than a
 * discriminated union. Consumers should read specific keys defensively.
 */
export type VerifyDetails = Record<string, unknown>;

export interface VerifyResponse {
  record_id: string;
  verdict: Verdict;
  headline: string;
  decided_by: ReasonTier | null;
  identity_binding: IdentityBinding;
  reasons: ReasonItem[];
  advisory: ReasonItem[];
  details: VerifyDetails;
  disclaimer: string;
}

export interface HealthResponse {
  status: string;
  uidai_certificate_loaded: boolean;
  uidai_certificate_fingerprint: string | null;
  uidai_certificate_pinned: boolean;
  consent_enforcement: boolean;
  consent_subjects_configured: number;
}

export interface ReasonsResponse {
  reasons: Record<string, string>;
}

export interface HistoryRecord {
  id: string;
  created_at: string;
  doc_type: string;
  qr_version: string | null;
  verdict: Verdict;
  decided_by: string | null;
  binding: IdentityBinding;
  reason_codes: string[];
  advisory_codes: string[];
  face_distance: number | null;
  liveness: string | null;
}

export interface HistoryResponse {
  records: HistoryRecord[];
  disclaimer: string;
}

export interface SummaryTrendPoint {
  day: string;
  verdict: string;
  count: number;
}

export interface SummaryTopReason {
  code: string;
  count: number;
}

export interface SummaryResponse {
  by_verdict: Record<string, number>;
  by_doc_type: Record<string, number>;
  trend: SummaryTrendPoint[];
  top_reasons: SummaryTopReason[];
  disclaimer: string;
}

export type DocumentKind = "aadhaar" | "aadhaar-full" | "pan" | "marksheet" | "face";
