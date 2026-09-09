import { useEffect, useRef, useState } from "react";

interface HomeViewProps {
  onStartCheck: () => void;
  onStartFace: () => void;
  onViewDashboard: () => void;
}

export function HomeView({ onStartCheck, onStartFace, onViewDashboard }: HomeViewProps) {
  return (
    <div className="home">
      <div className="home-intro-grid">
        <section className="hero">
          <h1 className="hero__title">Check a document<br />or compare a face.</h1>
          <p className="hero__subtitle">
            Upload an Aadhaar, PAN card, or marksheet to check its details.
            You can also compare an ID photo with a live camera capture.
          </p>
          <div className="hero__actions">
            <button type="button" className="button button--primary" onClick={onStartCheck}>Check a document</button>
            <button type="button" className="button button--secondary" onClick={onStartFace}>Compare a face</button>
          </div>
          <button type="button" className="hero__text-link" onClick={onViewDashboard}>
            View previous checks
          </button>
        </section>
        <SyntheticScan />
      </div>

      <section className="home-limits" aria-labelledby="limits-title">
        <h2 id="limits-title">About these checks</h2>
        <p>This tool checks document consistency and Aadhaar QR signatures. It does not query government databases or provide official verification. Face matching and liveness are reported separately; deepfake detection is not available.</p>
      </section>
    </div>
  );
}

function SyntheticScan() {
  const [channel, setChannel] = useState<"surface" | "signal">("surface");
  const [scanning, setScanning] = useState(false);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
  }, []);

  function runScan() {
    if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
    setChannel("surface");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setScanning(!reduceMotion);
    timeoutRef.current = window.setTimeout(() => {
      setScanning(false);
      setChannel("signal");
    }, reduceMotion ? 0 : 2800);
  }

  return (
    <figure className={`synthetic-scan${scanning ? " is-scanning" : ""}`}>
      <div className="synthetic-scan__topline">
        <span>Sample document</span>
        <span className="synthetic-scan__state">{scanning ? "Scanning…" : channel === "signal" ? "Preview ready" : "Preview"}</span>
      </div>
      <div className={`synthetic-scan__stage synthetic-scan__stage--${channel}`}>
        <div className="synthetic-card" aria-label="Sample document with fictional details">
          <div className="synthetic-card__portrait"><span /></div>
          <div className="synthetic-card__copy"><b>Sample ID</b><i /><i /><i className="short" /><small>Fictional details</small></div>
        </div>
        <div className="synthetic-scan__heatmap" aria-hidden="true" />
        <div className="synthetic-scan__line" aria-hidden="true" />
      </div>
      <div className="synthetic-scan__controls">
        <div role="group" aria-label="Sample view">
          <button type="button" aria-pressed={channel === "surface"} onClick={() => setChannel("surface")}>Original</button>
          <button type="button" aria-pressed={channel === "signal"} onClick={() => setChannel("signal")}>Heatmap</button>
        </div>
        <button type="button" className="synthetic-scan__run" onClick={runScan} disabled={scanning}>{scanning ? "Scanning…" : "Run sample scan"}</button>
      </div>
      <figcaption>A sample preview, not a verification result. Upload your document to run a check.</figcaption>
    </figure>
  );
}
