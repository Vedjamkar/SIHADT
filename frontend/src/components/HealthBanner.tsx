import type { HealthResponse } from "../types/api";

interface HealthBannerProps {
  health: HealthResponse | null;
  error: string | null;
}

/**
 * Surfaces backend health: whether the UIDAI certificate is loaded and
 * pinned (without it the cryptographic tier is unavailable; structural and
 * advisory findings may still be returned) and whether the face-pipeline
 * model files are present (without them face match, age gap, and liveness
 * fail fast rather than downloading mid-request).
 */
export function HealthBanner({ health, error }: HealthBannerProps) {
  if (error) {
    return (
      <div className="health-banner health-banner--unknown" data-anim="health-banner">
        <span className="health-banner-dot" />
        <span>Backend status unknown: {error}</span>
      </div>
    );
  }

  if (!health) {
    return (
      <div className="health-banner health-banner--loading" data-anim="health-banner">
        <span className="health-banner-dot" />
        <span>Checking backend status…</span>
      </div>
    );
  }

  const certOk = health.uidai_certificate_loaded;
  const modelsOk = health.face_models_ready;
  const tone = !certOk ? "bad" : health.uidai_certificate_pinned && modelsOk ? "good" : "warn";

  return (
    <div className={`health-banner health-banner--${tone}`} data-anim="health-banner">
      <span className="health-banner-dot" />
      <span className="health-banner-text">
        {certOk ? (
          health.uidai_certificate_pinned ? (
            <>UIDAI certificate loaded and pinned by fingerprint.</>
          ) : (
            <>
              UIDAI certificate loaded, but <strong>not pinned</strong> — trust
              relies on the file at the configured path only.
            </>
          )
        ) : (
          <>
            <strong>No UIDAI certificate loaded.</strong> Aadhaar signatures cannot
            be checked until UIDAI_CERT_PATH points to a valid certificate. Structural
            and advisory checks may still produce a finding.
          </>
        )}
      </span>
      {!modelsOk && (
        <span className="health-banner-text health-banner-models">
          <strong>Face models missing</strong> ({health.face_models_missing.length} file(s)) — face
          match, age gap, and liveness are unavailable until{" "}
          <code>python tools/fetch_models.py</code> has run.
        </span>
      )}
      <span className="health-banner-consent">
        Consent enforcement:{" "}
        {health.consent_enforcement
          ? `on (${health.consent_subjects_configured} subject(s) configured)`
          : "off"}
      </span>
    </div>
  );
}
