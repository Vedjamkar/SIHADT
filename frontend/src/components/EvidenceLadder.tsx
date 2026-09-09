import type { ReasonItem, ReasonTier } from "../types/api";

interface EvidenceLadderProps {
  decidedBy: ReasonTier | null;
  reasons: ReasonItem[];
  advisory: ReasonItem[];
}

type Rung = ReasonTier | "none";

/**
 * The evidence-strength ladder — deliberately NOT a percentage.
 *
 * A percentage score would be the easiest way to lose a judge (or a
 * user): there is no such number, and the whole tiered-reason
 * architecture in this backend exists specifically to avoid claiming
 * one. This shows WHICH TIER OF EVIDENCE WAS REACHED instead, and every
 * filled segment is defensible on its own terms:
 *
 *   - cryptographic and structural checks are deterministic — either the
 *     check ran and produced a conclusive result, or it did not run at
 *     all. So when one of those tiers decides the verdict, its rung
 *     fills completely: there is no such thing as a "60% signature
 *     check". A genuine Aadhaar fills the whole bar because it
 *     genuinely reached cryptographic proof — whether that proof came
 *     back positive (GENUINE_SIGNED) or negative (FORGED_SIGNATURE) is
 *     a separate question from how STRONG the evidence is, which is all
 *     this widget claims.
 *   - heuristic evidence is advisory by nature and is never drawn as
 *     strong even when it's the best available. Its rung fills only as
 *     many segments as there are actual named heuristic signals in this
 *     response (see reasons/advisory below), capped at a short ceiling —
 *     a PAN fills exactly one segment, because format-checking is
 *     genuinely all that exists to check for it.
 *
 * `decided_by` picks which rung is "reached". When it's null (every
 * PAN, every marksheet, and every other UNVERIFIABLE route), we still
 * look at the advisory reasons to show which tier of evidence was
 * actually observed even though nothing there was strong enough to
 * decide anything — that's the honest, neutral case, not a zero.
 */
export function EvidenceLadder({ decidedBy, reasons, advisory }: EvidenceLadderProps) {
  const combined = [...reasons, ...advisory];
  const countAt = (tier: ReasonTier) => combined.filter((r) => r.tier === tier).length;

  // decidedBy is null for every UNVERIFIABLE route, which is not a failure —
  // it means no tier was strong enough to decide. Start at "none" and let the
  // observed reasons say what evidence was actually seen.
  let reached: Rung = decidedBy ?? "none";
  if (reached === "none") {
    if (countAt("cryptographic") > 0) reached = "cryptographic";
    else if (countAt("structural") > 0) reached = "structural";
    else if (countAt("heuristic") > 0) reached = "heuristic";
    else reached = "none";
  }

  const RUNGS: { tier: Rung; label: string; segments: number }[] = [
    { tier: "cryptographic", label: "Cryptographic proof", segments: 12 },
    { tier: "structural", label: "Structural checks", segments: 8 },
    { tier: "heuristic", label: "Heuristic signals", segments: 4 },
    { tier: "none", label: "No evidence", segments: 0 },
  ];

  const heuristicCount = Math.max(1, countAt("heuristic"));

  return (
    <section className="evidence-ladder" aria-label="Evidence strength reached">
      <h3 className="evidence-ladder__title">Evidence reached</h3>
      <ul className="evidence-ladder__list">
        {RUNGS.map((rung) => {
          const isReached = rung.tier === reached;
          const filled =
            !isReached || rung.tier === "none"
              ? 0
              : rung.tier === "heuristic"
                ? Math.min(heuristicCount, rung.segments)
                : rung.segments; // cryptographic / structural: binary once reached — full rung.

          return (
            <li
              key={rung.tier}
              className={
                `evidence-ladder__rung evidence-ladder__rung--${rung.tier}` +
                (isReached ? " is-reached" : "")
              }
            >
              <span className="evidence-ladder__label">{rung.label}</span>
              {rung.tier === "none" ? (
                <span className="evidence-ladder__dash" aria-hidden="true">
                  —
                </span>
              ) : (
                <span className="evidence-ladder__bar" aria-hidden="true">
                  {Array.from({ length: rung.segments }).map((_, i) => (
                    <span
                      key={i}
                      className={"evidence-ladder__segment" + (i < filled ? " is-filled" : "")}
                    />
                  ))}
                </span>
              )}
              {isReached ? <span className="evidence-ladder__marker">← reached</span> : null}
            </li>
          );
        })}
      </ul>
      <p className="evidence-ladder__note">{noteFor(reached, heuristicCount)}</p>
    </section>
  );
}

function noteFor(reached: Rung, heuristicCount: number): string {
  switch (reached) {
    case "cryptographic":
      return "A digital signature was checked and produced a conclusive result — the strongest evidence this tool can reach.";
    case "structural":
      return "No signature exists to check here; an arithmetic or checksum rule was checked instead and produced a conclusive result.";
    case "heuristic":
      return `${heuristicCount} heuristic signal${heuristicCount === 1 ? "" : "s"} observed — advisory only, never strong enough to decide a verdict on its own.`;
    case "none":
    default:
      return "Nothing here produced even an advisory signal.";
  }
}
