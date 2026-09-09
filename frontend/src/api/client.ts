/**
 * The one place that talks to the backend. No fetch/XHR calls anywhere
 * else in this codebase — components call the functions below and get
 * typed responses or an ApiError.
 */
import { ApiError, extractDetail } from "./errors";
import type {
  HealthResponse,
  HistoryResponse,
  ReasonsResponse,
  SummaryResponse,
  VerifyResponse,
} from "../types/api";

export const API_BASE_URL =
  ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() ||
  "http://localhost:8000").replace(/\/+$/, "");

const METADATA_TIMEOUT_MS = 15_000;
const VERIFY_TIMEOUT_MS = 180_000;
const VERDICTS = ["GENUINE_SIGNED", "FORGED_SIGNATURE", "SIGNED_BUT_ALTERED", "STRUCTURALLY_INVALID", "UNVERIFIABLE", "NEEDS_REVIEW"];
const BINDINGS = ["BOUND", "NOT_BOUND", "LIVENESS_FAILED", "NOT_ATTEMPTED", "CHECK_FAILED"];

function invalidResponse(): ApiError {
  return new ApiError(502, "The verification server returned an unreadable response. Please try again.");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Reject empty/HTML success responses before they can crash a result view. */
function parseBody(text: string): unknown {
  try { return JSON.parse(text); } catch { return undefined; }
}

function validateVerification(body: unknown): void {
  const tiers = ["cryptographic", "structural", "heuristic"];
  const reasonsValid = (value: unknown) => Array.isArray(value) && value.every(item =>
    isRecord(item) && typeof item.code === "string" && typeof item.message === "string" && tiers.includes(String(item.tier)));
  if (!isRecord(body) || !VERDICTS.includes(String(body.verdict)) ||
      !BINDINGS.includes(String(body.identity_binding)) || typeof body.record_id !== "string" ||
      typeof body.headline !== "string" || typeof body.disclaimer !== "string" ||
      (body.decided_by !== null && !tiers.includes(String(body.decided_by))) ||
      !isRecord(body.details) || !reasonsValid(body.reasons) || !reasonsValid(body.advisory)) {
    throw invalidResponse();
  }
}

/** Check fields consumed by the dashboard instead of trusting a TS cast. */
function validateMetadata(path: string, body: unknown): void {
  if (!isRecord(body)) throw invalidResponse();
  const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === "string");
  const counts = (value: unknown) => isRecord(value) && Object.values(value).every(item =>
    typeof item === "number" && Number.isFinite(item) && item >= 0);
  let valid = false;
  if (path === "/health") {
    valid = typeof body.status === "string" && typeof body.uidai_certificate_loaded === "boolean" &&
      typeof body.uidai_certificate_pinned === "boolean" && typeof body.consent_enforcement === "boolean" &&
      typeof body.consent_subjects_configured === "number";
  } else if (path === "/reasons") {
    valid = isRecord(body.reasons) && Object.values(body.reasons).every(item => typeof item === "string");
  } else if (path.startsWith("/dashboard/history")) {
    valid = typeof body.disclaimer === "string" && Array.isArray(body.records) && body.records.every(row =>
      isRecord(row) && typeof row.id === "string" && typeof row.created_at === "string" &&
      typeof row.doc_type === "string" && VERDICTS.includes(String(row.verdict)) &&
      BINDINGS.includes(String(row.binding)) && strings(row.reason_codes) && strings(row.advisory_codes));
  } else if (path === "/dashboard/summary") {
    valid = typeof body.disclaimer === "string" && counts(body.by_verdict) && counts(body.by_doc_type) &&
      Array.isArray(body.trend) && body.trend.every(point => isRecord(point) && typeof point.day === "string" &&
        typeof point.verdict === "string" && typeof point.count === "number" && Number.isFinite(point.count) && point.count >= 0) &&
      Array.isArray(body.top_reasons) && body.top_reasons.every(reason => isRecord(reason) &&
        typeof reason.code === "string" && typeof reason.count === "number" && Number.isFinite(reason.count) && reason.count >= 0);
  }
  if (!valid) throw invalidResponse();
}

/** Plain GET/JSON requests (dashboard, health, reasons). */
async function getJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), METADATA_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { method: "GET", signal: controller.signal });
    // Include the body read in the timeout: headers alone are not completion.
    const body = await handleResponse<T>(response);
    validateMetadata(path, body);
    return body;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) {
      throw new ApiError(0, "The verification server took too long to respond. Please try again.");
    }
    throw new ApiError(
      0,
      "Could not reach the verification server. Confirm it is running at " +
        API_BASE_URL +
        " and that your connection is up.",
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const body = parseBody(text);

  if (!response.ok) {
    const fallback = `Request failed (HTTP ${response.status}).`;
    throw new ApiError(response.status, extractDetail(body, fallback));
  }

  if (!isRecord(body)) throw invalidResponse();
  return body as T;
}

/**
 * Multipart POST with real upload-progress reporting. fetch() cannot report
 * upload progress, so this uses XMLHttpRequest deliberately.
 */
function postForm<T>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.timeout = VERIFY_TIMEOUT_MS;

    // This event marks bytes sent, not a completed server analysis.
    xhr.upload.onload = () => onProgress?.(1);
    xhr.ontimeout = () => reject(new ApiError(0,
      "This check took too long to respond. The server may still finish it; check the dashboard before submitting again."));
    xhr.onabort = () => reject(new ApiError(0, "The upload was cancelled. You can try again."));

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(event.loaded / event.total);
      }
    };

    xhr.onerror = () => {
      reject(
        new ApiError(
          0,
          "Could not reach the verification server. Confirm it is running at " +
            API_BASE_URL +
            " and that your connection is up.",
        ),
      );
    };

    xhr.onload = () => {
      const body = parseBody(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          validateVerification(body);
          resolve(body as T);
        } catch (error) {
          reject(error);
        }
      } else {
        const fallback = `Request failed (HTTP ${xhr.status}).`;
        reject(new ApiError(xhr.status, extractDetail(body, fallback)));
      }
    };

    xhr.send(form);
  });
}

// ---------------------------------------------------------------------------
// Verify endpoints
// ---------------------------------------------------------------------------

export function verifyAadhaar(
  document: File,
  backDocument: File | null,
  onProgress?: (fraction: number) => void,
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("document", document);
  if (backDocument) form.append("back_document", backDocument);
  return postForm<VerifyResponse>("/verify/aadhaar", form, onProgress);
}

export interface AadhaarFullParams {
  document: File;
  backDocument: File | null;
  frames: File[];
  consentSubject: string;
  challenge?: "blink" | "head_turn";
}

export function verifyAadhaarFull(
  params: AadhaarFullParams,
  onProgress?: (fraction: number) => void,
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("document", params.document);
  if (params.backDocument) form.append("back_document", params.backDocument);
  for (const frame of params.frames) form.append("frames", frame);
  form.append("consent_subject", params.consentSubject);
  form.append("challenge", params.challenge ?? "blink");
  return postForm<VerifyResponse>("/verify/aadhaar-full", form, onProgress);
}

export function verifyPan(
  document: File,
  onProgress?: (fraction: number) => void,
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("document", document);
  return postForm<VerifyResponse>("/verify/pan", form, onProgress);
}

export function verifyMarksheet(
  document: File,
  subjects: [string, string, string, string, string],
  onProgress?: (fraction: number) => void,
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("document", document);
  subjects.forEach((subject, index) => {
    form.append(`subject${index + 1}`, subject);
  });
  return postForm<VerifyResponse>("/verify/marksheet", form, onProgress);
}

export interface FaceVerifyParams {
  idPhoto: File;
  frames: File[];
  consentSubject: string;
  challenge?: "blink" | "head_turn";
}

export function verifyFace(
  params: FaceVerifyParams,
  onProgress?: (fraction: number) => void,
): Promise<VerifyResponse> {
  const form = new FormData();
  form.append("id_photo", params.idPhoto);
  for (const frame of params.frames) form.append("frames", frame);
  form.append("consent_subject", params.consentSubject);
  form.append("challenge", params.challenge ?? "blink");
  return postForm<VerifyResponse>("/verify/face", form, onProgress);
}

// ---------------------------------------------------------------------------
// Dashboard / metadata endpoints
// ---------------------------------------------------------------------------

export function getHistory(limit = 50): Promise<HistoryResponse> {
  return getJson<HistoryResponse>(`/dashboard/history?limit=${limit}`);
}

export function getSummary(): Promise<SummaryResponse> {
  return getJson<SummaryResponse>("/dashboard/summary");
}

export function getReasons(): Promise<ReasonsResponse> {
  return getJson<ReasonsResponse>("/reasons");
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}

export { ApiError };
