import type { ReasonItem, ReasonTier, VerifyDetails, Verdict } from "../types/api";
import { TIER_LABEL, VERDICT_COPY } from "../lib/copy";

interface ResultInterpretationProps {
  verdict: Verdict;
  decidedBy: ReasonTier | null;
  reasons: ReasonItem[];
  advisory: ReasonItem[];
  details: VerifyDetails;
}

const GUIDANCE: Record<Verdict, { title: string; body: string }> = {
  GENUINE_SIGNED: {
    title: "The signed document data passed its strongest available check.",
    body: "You can rely on the signed QR data for this check. Confirm identity separately if you need to know whether the document belongs to the person presenting it.",
  },
  FORGED_SIGNATURE: {
    title: "Pause this verification and review the source document.",
    body: "The issuer signature did not validate. Re-scan the original document and compare it with a trusted issuer-provided copy before making a decision.",
  },
  SIGNED_BUT_ALTERED: {
    title: "Review the printed document against its signed QR data.",
    body: "The QR is signed, but the visible card conflicts with it. Check the named fields below and request a fresh issuer-provided document.",
  },
  STRUCTURALLY_INVALID: {
    title: "Check the document values before accepting it.",
    body: "A deterministic rule such as a checksum or total did not agree. Use the explanation below to locate the mismatch and verify it against the original source.",
  },
  UNVERIFIABLE: {
    title: "Do not treat this result as either a pass or a failure.",
    body: "This check did not reach independent proof. Use an issuer source or another verification method if a conclusive decision is required.",
  },
  NEEDS_REVIEW: {
    title: "Human review is recommended.",
    body: "Advisory signals crossed the review threshold. They can occur in ordinary scans, so inspect the named areas and compare with the original document rather than rejecting it automatically.",
  },
};

export function ResultInterpretation({ verdict, decidedBy, reasons, advisory, details }: ResultInterpretationProps) {
  const guidance = GUIDANCE[verdict];
  const outcomeIsAdvisory = verdict === "NEEDS_REVIEW";
  const advisorySignals = outcomeIsAdvisory
    ? reasons.filter((reason) => reason.tier === "heuristic")
    : advisory;

  return (
    <>
      <aside
        className={`result-guidance result-guidance--${VERDICT_COPY[verdict].tone}`}
        aria-labelledby="result-guidance-title"
        role={outcomeIsAdvisory ? "alert" : "status"}
      >
        <div className="result-guidance__label">
          {outcomeIsAdvisory ? "Advisory — review before deciding" : "Recommended next step"}
        </div>
        <h3 id="result-guidance-title">{guidance.title}</h3>
        <p>{guidance.body}</p>
        {outcomeIsAdvisory ? (
          <strong className="result-guidance__caution">This is a review prompt, not proof of alteration.</strong>
        ) : null}
      </aside>

      <section className="decision-explanation" aria-labelledby="decision-explanation-title">
        <header className="decision-explanation__header">
          <div>
            <h3 id="decision-explanation-title">How this result was reached</h3>
            <p>
              {reasons.length + advisory.length} observation{reasons.length + advisory.length === 1 ? "" : "s"} reported
            </p>
          </div>
        </header>

        <div className="decision-step decision-step--basis">
          <div>
            <h4>Evidence level</h4>
            <p>
              {decidedBy
                ? `${TIER_LABEL[decidedBy]} evidence determined the document result.`
                : "No evidence tier was strong enough to determine authenticity."}
            </p>
          </div>
        </div>

        <div className="decision-step decision-step--decisive">
          <div>
            <h4>{outcomeIsAdvisory ? "Signals that triggered the advisory" : "Findings that affected the result"}</h4>
            <InterpretationReasons
              reasons={reasons}
              empty="No observation was strong enough to affect the document result."
              label="Affected outcome"
            />
          </div>
        </div>

        <div className="decision-step decision-step--supporting">
          <div>
            <h4>Supporting observations</h4>
            {outcomeIsAdvisory && advisory.length === 0 ? (
              <p>The heuristic signals above are the advisory basis; there were no additional observations.</p>
            ) : (
              <InterpretationReasons
                reasons={advisory}
                empty="No additional advisory observations were reported."
                label="Advisory only"
              />
            )}
          </div>
        </div>

        <KeyReadings details={details} advisoryCount={advisorySignals.length} />
      </section>
    </>
  );
}

function InterpretationReasons({ reasons, empty, label }: { reasons: ReasonItem[]; empty: string; label: string }) {
  if (reasons.length === 0) return <p className="decision-step__empty">{empty}</p>;

  return (
    <ul className="interpretation-reasons">
      {reasons.map((reason) => (
        <li key={reason.code} className={`interpretation-reason interpretation-reason--${reason.tier}`}>
          <span className="interpretation-reason__status">{label}</span>
          <p>{reason.message}</p>
          <span className="interpretation-reason__meta">
            {TIER_LABEL[reason.tier]} · <code>{reason.code}</code>
          </span>
        </li>
      ))}
    </ul>
  );
}

interface KeyReading {
  label: string;
  value: string;
  explanation: string;
  tone: "violet" | "cyan" | "coral" | "lime";
}

function KeyReadings({ details, advisoryCount }: { details: VerifyDetails; advisoryCount: number }) {
  const readings = buildReadings(details, advisoryCount);
  if (readings.length === 0) return null;

  return (
    <div className="key-readings">
      <div className="key-readings__heading">
        <h4>Key readings, translated</h4>
        <span>What the raw values mean</span>
      </div>
      <dl className="key-readings__list">
        {readings.map((reading) => (
          <div className={`key-reading key-reading--${reading.tone}`} key={reading.label}>
            <dt>{reading.label}</dt>
            <dd>
              <strong>{reading.value}</strong>
              <span>{reading.explanation}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function buildReadings(details: VerifyDetails, advisoryCount: number): KeyReading[] {
  const readings: KeyReading[] = [];
  const signature = details.signature_verified;
  if (typeof signature === "boolean") {
    readings.push({
      label: "Digital signature",
      value: signature ? "Validated" : "Did not validate",
      explanation: signature
        ? "The QR data matched the issuer's digital signature."
        : "The QR data could not be authenticated with the issuer signature.",
      tone: signature ? "cyan" : "coral",
    });
  } else if (signature === null) {
    readings.push({
      label: "Digital signature",
      value: "Not available",
      explanation: "A signature check could not be completed for this result.",
      tone: "violet",
    });
  }

  if (typeof details.qr_version === "string" && details.qr_version) {
    readings.push({
      label: "QR format",
      value: details.qr_version,
      explanation: "The QR payload format detected in the supplied document.",
      tone: "violet",
    });
  }

  const mrz = asRecord(details.mrz);
  const mrzChecks = asRecord(mrz?.checks);
  if (details.mrz_found === true && mrzChecks) {
    const checks = Object.values(mrzChecks).filter((value): value is boolean => typeof value === "boolean");
    const passed = checks.filter(Boolean).length;
    const allPassed = checks.length > 0 && passed === checks.length;
    readings.push({
      label: "MRZ check digits",
      value: allPassed ? "All passed" : `${passed} of ${checks.length} passed`,
      explanation: allPassed
        ? "The machine-readable passport fields are internally consistent. This does not authenticate the passport chip."
        : "One or more machine-readable fields disagreed with its check digit. A clearer scan may be needed before reviewing the document.",
      tone: allPassed ? "cyan" : "coral",
    });
  } else if (details.mrz_found === false) {
    readings.push({
      label: "Machine-readable zone",
      value: "Not detected",
      explanation: "Keep both MRZ lines at the bottom of the photo page sharp, straight, and fully inside the image.",
      tone: "violet",
    });
  }

  if (typeof mrz?.expiry_date === "string" && mrz.expiry_date.length === 6) {
    readings.push({
      label: "MRZ expiry",
      value: mrz.expiry_date,
      explanation: "Expiry date read from the machine-readable zone in YYMMDD format.",
      tone: "violet",
    });
  }

  const ela = asRecord(details.ela);
  const fraction = ela?.flagged_fraction;
  if (typeof fraction === "number" && Number.isFinite(fraction)) {
    const blocks = ela?.flagged_blocks;
    const blockText = typeof blocks === "number" ? ` across ${blocks} highlighted blocks` : "";
    readings.push({
      label: "Compression variation",
      value: `${(fraction * 100).toFixed(fraction < 0.01 ? 2 : 1)}%`,
      explanation: `Variation appeared in this share of the analysed image${blockText}. This is advisory and does not prove editing by itself.`,
      tone: fraction > 0 ? "coral" : "cyan",
    });
  }

  const computed = details.computed_total;
  const printed = details.printed_total;
  if (typeof computed === "number" && typeof printed === "number") {
    const matches = computed === printed;
    readings.push({
      label: "Document total",
      value: matches ? `${computed} — matches` : `${computed} calculated / ${printed} printed`,
      explanation: matches
        ? "The calculated subject total agrees with the total printed on the document."
        : "The calculated and printed totals disagree and should be checked against the original.",
      tone: matches ? "lime" : "coral",
    });
  }

  if (readings.length < 2 && advisoryCount > 0) {
    readings.push({
      label: "Advisory signals",
      value: String(advisoryCount),
      explanation: "These observations provide context but cannot establish authenticity on their own.",
      tone: "violet",
    });
  }

  return readings.slice(0, 4);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}
