import type { ReasonTier, Verdict } from "../types/api";
import { TIER_LABEL, VERDICT_COPY } from "../lib/copy";

interface VerdictCardProps {
  verdict: Verdict;
  /** The backend's own one-line headline, shown as a secondary caption. */
  headline: string;
  decidedBy: ReasonTier | null;
}

/**
 * Renders the verdict on its own — never combined with identity binding in
 * the same badge or card (see BindingBadge, rendered separately). The tone
 * class (`verdict-card--genuine-signed`, `--unverifiable`, etc.) is defined
 * in styles/components.css; UNVERIFIABLE deliberately loses the accent
 * rail there so it recedes rather than reading as a failure.
 */
export function VerdictCard({ verdict, headline, decidedBy }: VerdictCardProps) {
  const copy = VERDICT_COPY[verdict];

  return (
    <section className={`verdict-card verdict-card--${copy.tone}`} aria-label="Document verdict">
      <p className="verdict-card__eyebrow">Document check</p>
      <h2 className="verdict-card__title">{copy.title}</h2>
      <p className="verdict-card__claim">{headline}</p>
      <p className="verdict-card__description">{copy.description}</p>
      {decidedBy ? (
        <div className="verdict-card__meta">
          <span className={`tier-badge tier-badge--${decidedBy}`}>
            Decided by: {TIER_LABEL[decidedBy]}
          </span>
        </div>
      ) : null}
    </section>
  );
}
