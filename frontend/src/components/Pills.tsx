import type { IdentityBinding, Verdict } from "../types/api";
import { BINDING_COPY, VERDICT_COPY } from "../lib/copy";

/**
 * Compact pill versions of VerdictCard/BindingBadge for dense contexts
 * (the dashboard history table). Same tone vocabulary, smaller footprint —
 * still two separate elements, never merged.
 */
export function VerdictPill({ verdict }: { verdict: Verdict }) {
  const copy = VERDICT_COPY[verdict];
  return (
    <span className={`verdict-pill verdict-pill--${copy.tone}`}>{copy.title}</span>
  );
}

export function BindingPill({ binding }: { binding: IdentityBinding }) {
  const copy = BINDING_COPY[binding];
  return (
    <span className={`binding-pill binding-pill--${copy.tone}`}>{copy.title}</span>
  );
}
