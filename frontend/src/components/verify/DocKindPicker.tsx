import type { DocumentKind } from "../../types/api";
import { DOC_KIND_INFO } from "../../lib/copy";

interface DocKindPickerProps {
  onSelect: (kind: DocumentKind) => void;
}

const ORDER: DocumentKind[] = ["aadhaar", "aadhaar-full", "passport", "pan", "marksheet"];

/**
 * The first screen of the verify flow: choose a document type before
 * anything else. Each card states its ceiling up front — PAN and
 * marksheet say plainly that UNVERIFIABLE is the best possible outcome,
 * so that result never reads as a letdown later.
 */
export function DocKindPicker({ onSelect }: DocKindPickerProps) {
  return (
    <div className="kind-picker">
      <h2 className="kind-picker__title">What are you checking?</h2>
      <p className="kind-picker__subtitle">
        The document type decides what can actually be proven — pick one to see what to
        upload.
      </p>
      <div className="kind-picker__grid" data-anim="kind-picker-grid">
        {ORDER.map((kind) => {
          const info = DOC_KIND_INFO[kind];
          return (
            <button
              key={kind}
              type="button"
              className="kind-card"
              data-anim="kind-card"
              onClick={() => onSelect(kind)}
            >
              <span className={`kind-card__ceiling kind-card__ceiling--${info.ceiling}`}>
                {info.ceiling === "cryptographic" ? "Cryptographic check" : "Structural check only"}
              </span>
              <h3 className="kind-card__label">{info.label}</h3>
              <p className="kind-card__tagline">{info.tagline}</p>
              <p className="kind-card__description">{info.description}</p>
              <p className="kind-card__ceiling-note">{info.ceilingNote}</p>
              <span className="kind-card__cta">Start with {info.label} →</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
