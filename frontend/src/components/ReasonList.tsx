import type { ReasonItem } from "../types/api";
import { TIER_LABEL, TIER_ORDER } from "../lib/copy";

interface ReasonListProps {
  title: string;
  reasons: ReasonItem[];
  emptyMessage?: string;
}

/**
 * Reasons are always rendered as plain-language sentences (reason.message),
 * grouped by tier (cryptographic / structural / heuristic). A raw code is
 * never the primary message — it's shown small, for reference only.
 */
export function ReasonList({ title, reasons, emptyMessage }: ReasonListProps) {
  const byTier = new Map<string, ReasonItem[]>();
  for (const reason of reasons) {
    const bucket = byTier.get(reason.tier) ?? [];
    bucket.push(reason);
    byTier.set(reason.tier, bucket);
  }

  return (
    <section className="reason-section">
      <h3 className="reason-section__title">{title}</h3>
      {reasons.length === 0 ? (
        <p className="reason-empty">{emptyMessage ?? "None."}</p>
      ) : (
        TIER_ORDER.filter((tier) => byTier.has(tier)).map((tier) => (
          <div className="reason-tier-group" key={tier}>
            <span className={`tier-badge tier-badge--${tier}`}>{TIER_LABEL[tier]}</span>
            <ul className="reason-list" data-anim="reason-list">
              {byTier.get(tier)!.map((reason) => (
                <li
                  className={`reason-item reason-item--${tier}`}
                  key={reason.code}
                  data-anim="reason-item"
                >
                  <div className="reason-item__body">
                    <p className="reason-item__text">{reason.message}</p>
                    <code className="reason-item__code">{reason.code}</code>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
