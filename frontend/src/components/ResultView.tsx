import { useEffect, useRef } from "react";
import type { VerifyResponse } from "../types/api";
import { VerdictCard } from "./VerdictCard";
import { BindingBadge } from "./BindingBadge";
import { EvidenceLadder } from "./EvidenceLadder";
import { ReasonList } from "./ReasonList";
import { DetailsPanel } from "./DetailsPanel";
import { Disclaimer } from "./Disclaimer";
import { animateVerdictReveal } from "../motion";
import { FaceEvidence } from "./FaceEvidence";

interface ResultViewProps {
  result: VerifyResponse;
  onCheckAnother: () => void;
}

/**
 * The result, read as a considered finding rather than a pass/fail
 * banner. Kept visually and structurally separate, in this order:
 *   1. What was proven or disproven about the document (verdict).
 *   2. How strong the evidence behind that was (the ladder — a tier
 *      reached, never a percentage).
 *   3. The reasons that decided it, then what else was observed but
 *      did not decide anything (advisory).
 *   4. Whether the document is bound to the person presenting it — a
 *      completely different question, never merged into the verdict.
 *
 * The whole result settles in with a single, quiet motion (see
 * src/motion) keyed to the record id — not three separate staged
 * reveals stacked down the page. A fresh result always replays that one
 * settle even if the DOM nodes are reused.
 */
export function ResultView({ result, onCheckAnother }: ResultViewProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    animateVerdictReveal(rootRef.current);
    // Re-run whenever a genuinely new result arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.record_id]);

  return (
    <div className="result-view" ref={rootRef} data-anim="verdict-card">
      <VerdictCard verdict={result.verdict} headline={result.headline} decidedBy={result.decided_by} />

      <EvidenceLadder decidedBy={result.decided_by} reasons={result.reasons} advisory={result.advisory} />

      <div className="result-view__section">
        <ReasonList
          title="What this proves"
          reasons={result.reasons}
          emptyMessage="No checks reached a conclusive tier for this document."
        />
      </div>

      <div className="result-view__section">
        <ReasonList
          title="What could not be determined / other observations"
          reasons={result.advisory}
          emptyMessage="Nothing else notable."
        />
      </div>

      <div className="result-view__section">
        <BindingBadge binding={result.identity_binding} />
      </div>

      <FaceEvidence details={result.details} />

      <DetailsPanel details={result.details} />

      <Disclaimer text={result.disclaimer} />

      <div className="result-view__actions">
        <button type="button" className="button button--primary" onClick={onCheckAnother}>
          Check another document
        </button>
        <p className="result-view__record-id">
          Record ID: <code>{result.record_id}</code>
        </p>
      </div>
    </div>
  );
}
