/**
 * A single error shape for every failure mode the API surfaces:
 * HTTP 400 (bad input), 403 (consent not given), 413 (too large), other
 * HTTP errors, and network failure (status 0).
 *
 * `detail` is always a human-readable message — either the backend's own
 * `detail` string/array, or a message we generate for network-level
 * failures. Components should render `detail` directly; they should not
 * need to branch on `status` to get a sensible message, though `status`
 * is exposed for callers that want to special-case 403 (consent) styling.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isConsentError(): boolean {
    return this.status === 403;
  }

  get isTooLarge(): boolean {
    return this.status === 413;
  }
}

/** Best-effort extraction of a readable message from a FastAPI error body. */
export function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  return fallback;
}
