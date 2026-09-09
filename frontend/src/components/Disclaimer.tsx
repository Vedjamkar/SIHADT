interface DisclaimerProps {
  text: string;
}

/**
 * Always rendered wherever a `disclaimer` field arrives from the API.
 * This is not decorative — it is the thing standing between this tool and
 * a false claim of official government verification.
 */
export function Disclaimer({ text }: DisclaimerProps) {
  return (
    <p className="disclaimer-banner" data-anim="disclaimer">
      <svg className="disclaimer-banner__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.4" />
        <path d="M10 6.5v4.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="10" cy="13.4" r="0.9" fill="currentColor" />
      </svg>
      <span>{text}</span>
    </p>
  );
}
