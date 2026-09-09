import type { VerifyDetails } from "../types/api";

interface FaceEvidenceProps {
  details: VerifyDetails;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? value as Record<string, unknown> : null;
}

function formatScore(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Unavailable";
}

function formatDistance(value: unknown): string {
  return typeof value === "number" ? value.toFixed(3) : "Unavailable";
}

export function FaceEvidence({ details }: FaceEvidenceProps) {
  const face = asRecord(details.face);
  const liveness = asRecord(details.liveness);
  if (!face && !liveness) return null;

  const challenge = liveness?.challenge === "head_turn" ? "Head turn" : liveness?.challenge === "blink" ? "Blink" : "Not reported";
  const livenessState = liveness?.checked !== true
    ? "Not completed"
    : liveness.passed === true
      ? "Gesture observed"
      : liveness.passed === false
        ? "Gesture not observed"
        : "Inconclusive";

  return (
    <section className="face-evidence" aria-labelledby="face-evidence-title">
      <div className="face-evidence__header">
        <div>
          <h3 id="face-evidence-title">Face comparison</h3>
        </div>
        <span className="face-evidence__model">{typeof face?.model === "string" ? face.model : "Model not reported"}</span>
      </div>
      <dl className="face-evidence__readings">
        <div>
          <dt>Cosine distance</dt>
          <dd>{formatDistance(face?.distance)}</dd>
          <small>Lower means closer · similarity {formatScore(face?.similarity)}</small>
        </div>
        <div>
          <dt>Maximum match distance</dt>
          <dd>{formatDistance(face?.threshold)}</dd>
          <small>Distance must be at or below this boundary</small>
        </div>
        <div>
          <dt>Liveness prompt</dt>
          <dd>{challenge}</dd>
          <small>{livenessState}</small>
        </div>
        <div>
          <dt>Deepfake screen</dt>
          <dd>Unavailable</dd>
          <small>No replay or synthetic-face detector ran</small>
        </div>
      </dl>
      {typeof liveness?.detail === "string" && liveness.detail ? (
        <p className="face-evidence__detail">Liveness detail: {liveness.detail}</p>
      ) : null}
    </section>
  );
}
