import type { HealthResponse } from "../types/api";

interface HealthBannerProps {
  health: HealthResponse | null;
  error: string | null;
}

/**
 * Surfaces backend health, specifically whether the UIDAI certificate is
 * loaded and pinned. Without it, the cryptographic tier is unavailable;
 * structural and advisory findings may still be returned.
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
  const tone = certOk ? (health.uidai_certificate_pinned ? "good" : "warn") : "bad";

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
      <span className="health-banner-consent">
        Consent enforcement:{" "}
        {health.consent_enforcement
          ? `on (${health.consent_subjects_configured} subject(s) configured)`
          : "off"}
      </span>
    </div>
  );
}
