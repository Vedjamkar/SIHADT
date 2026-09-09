import type { DocumentKind } from "../../types/api";
import { CHECKING_STEPS } from "../../lib/copy";
import { ScanPreview } from "./ScanPreview";

interface CheckingStatusProps {
  kind: DocumentKind;
  /** The document being checked, shown under the sweep. */
  file?: File | null;
  /** 0..1 upload progress; sits at 1 while the server is still working. */
  progress: number;
}

/**
 * Replaces the form fields while a check is running so the wait reads as
 * "the system doing something specific" instead of a bare spinner. Steps
 * are illustrative of what the backend actually does for this document
 * kind (see lib/copy.ts CHECKING_STEPS) — they are not literally polled
 * from the server, since the API is a single request/response, but they
 * map onto real phases of that one request.
 *
 * The progress bar is honest about what it actually knows: `progress` is
 * a real 0..1 fraction reported by XMLHttpRequest's upload.onprogress
 * (see api/client.ts postForm) — genuine bytes-sent-over-bytes-total, not
 * a fabrication. Once the upload itself reaches 100%, that signal runs
 * out: the backend does a single request/response, not a job we can
 * poll, so there is no real number for "how much of the server-side
 * check is done". Rather than freeze at 100% (which reads as stuck) or
 * invent a fake number creeping upward, the bar switches to a plain
 * indeterminate sweep for that phase.
 */
export function CheckingStatus({ kind, progress, file = null }: CheckingStatusProps) {
  const steps = CHECKING_STEPS[kind];
  const percent = Math.round(Math.min(1, Math.max(0, progress)) * 100);
  const isProcessing = progress >= 1;

  return (
    <div className="checking-status" role="status" aria-live="polite">
      {/* Show the thing being examined. It confirms the right file was
          picked, and turns an abstract wait into something legible. */}
      <div className={`scan-preview-host${isProcessing || progress > 0 ? " scan-preview--scanning" : ""}`}>
        <ScanPreview
          file={file}
          stepLabel={isProcessing ? "Server analysis in progress" : `Sending document · ${percent}%`}
          processing={isProcessing}
        />
      </div>
      <div
        className="checking-status__progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={isProcessing ? undefined : percent}
        aria-label="Check progress"
      >
        <div
          className={
            "checking-status__progress-bar" + (isProcessing ? " checking-status__progress-bar--indeterminate" : "")
          }
          style={isProcessing ? undefined : { width: `${percent}%` }}
        />
      </div>

      <p className="checking-status__list-label">Checks included in this request</p>
      <ul className="checklist">
        {steps.map((label) => (
          <li
            key={label}
            className="checklist-item is-pending"
            data-anim="checklist-item"
          >
            <span className="checklist-item__label">{label}</span>
          </li>
        ))}
      </ul>
      <p className="checking-status__note">
        {isProcessing
          ? "Upload complete. Your results will appear when the analysis finishes."
          : `Uploading… ${percent}%`}
      </p>
    </div>
  );
}
