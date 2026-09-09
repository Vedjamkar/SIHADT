import { ApiError } from "../api/client";

interface ErrorPanelProps {
  error: ApiError;
}

/**
 * Renders every failure mode from the API client in plain language. The
 * backend's own `detail` string is always surfaced verbatim (it already
 * explains what went wrong); this component adds only the framing needed
 * to make each status code actionable.
 */
export function ErrorPanel({ error }: ErrorPanelProps) {
  const kind = classify(error);

  return (
    <section
      className={`error-panel error-panel--${kind}`}
      data-anim="error-panel"
      role="alert"
    >
      <p className="error-panel-title">{titleFor(kind)}</p>
      <p className="error-panel-detail">{error.detail}</p>
      {kind === "consent" ? (
        <p className="error-panel-hint">
          Face-matching in this tool requires the person's own explicit
          consent, on the record. Add their name to the server's
          CONSENT_SUBJECTS list before retrying — see the backend README.
        </p>
      ) : null}
      {kind === "too-large" ? (
        <p className="error-panel-hint">
          Try a smaller image (e.g. re-export at a lower resolution) — the
          server enforces a maximum upload size.
        </p>
      ) : null}
      {kind === "network" ? (
        <p className="error-panel-hint">
          Confirm the backend is running and reachable, and that CORS is
          configured for this app's origin.
        </p>
      ) : null}
    </section>
  );
}

type ErrorKind = "network" | "consent" | "too-large" | "bad-input" | "server" | "unknown";

function classify(error: ApiError): ErrorKind {
  if (error.isNetworkError) return "network";
  if (error.isConsentError) return "consent";
  if (error.isTooLarge) return "too-large";
  if (error.status === 400) return "bad-input";
  if (error.status >= 500) return "server";
  return "unknown";
}

function titleFor(kind: ErrorKind): string {
  switch (kind) {
    case "network":
      return "Could not reach the server";
    case "consent":
      return "Consent required";
    case "too-large":
      return "File too large";
    case "bad-input":
      return "This upload could not be processed";
    case "server":
      return "The server hit an error while processing this";
    default:
      return "Something went wrong";
  }
}
