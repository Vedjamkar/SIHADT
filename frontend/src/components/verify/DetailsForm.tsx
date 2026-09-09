import { useState } from "react";
import type { FormEvent } from "react";
import type { DocumentKind } from "../../types/api";
import type { SubmitPayload, UploadPhase } from "../../types/forms";
import { DOC_KIND_INFO } from "../../lib/copy";
import { FileDrop } from "../FileDrop";
import { ErrorPanel } from "../ErrorPanel";
import { CheckingStatus } from "./CheckingStatus";
import { ApiError } from "../../api/client";
import { ScanPreview } from "./ScanPreview";
import { FaceCapture } from "./FaceCapture";
import type { FaceChallenge } from "./FaceCapture";

interface DetailsFormProps {
  kind: DocumentKind;
  phase: UploadPhase;
  onBack: () => void;
  onSubmit: (payload: SubmitPayload) => void;
}

/**
 * The second screen of the verify flow: only the fields this document
 * kind actually needs, one clear column, with the document choice
 * (and its ceiling) still visible at the top as a reminder rather than a
 * silent assumption. While a check runs, this swaps its fields for
 * <CheckingStatus> instead of just disabling everything and hoping the
 * spinner is enough.
 */
export function DetailsForm({ kind, phase, onBack, onSubmit }: DetailsFormProps) {
  const info = DOC_KIND_INFO[kind];

  const [document, setDocument] = useState<File[]>([]);
  const [backDocument, setBackDocument] = useState<File[]>([]);
  const [frames, setFrames] = useState<File[]>([]);
  const [consentSubject, setConsentSubject] = useState("");
  const [subjects, setSubjects] = useState<string[]>(["", "", "", "", ""]);
  const [challenge, setChallenge] = useState<FaceChallenge>("blink");
  const [validationError, setValidationError] = useState<string | null>(null);

  const isUploading = phase.status === "uploading";
  const isChecking = isUploading; // one request/response; "checking" begins as soon as it's in flight

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setValidationError(null);

    if (document.length === 0) {
      setValidationError("Choose a document image (or PDF) to check.");
      return;
    }

    if (kind === "aadhaar") {
      onSubmit({ kind: "aadhaar", document: document[0], backDocument: backDocument[0] ?? null });
      return;
    }

    if (kind === "aadhaar-full") {
      if (frames.length < 3) {
        setValidationError("At least 3 live frames are required for identity binding.");
        return;
      }
      if (!consentSubject.trim()) {
        setValidationError("Name the consenting person this selfie belongs to.");
        return;
      }
      onSubmit({
        kind: "aadhaar-full",
        document: document[0],
        backDocument: backDocument[0] ?? null,
        frames,
        consentSubject: consentSubject.trim(),
        challenge,
      });
      return;
    }

    if (kind === "pan") {
      onSubmit({ kind: "pan", document: document[0] });
      return;
    }

    if (kind === "marksheet") {
      if (subjects.some((s) => !s.trim())) {
        setValidationError("All five subject names are required.");
        return;
      }
      onSubmit({
        kind: "marksheet",
        document: document[0],
        subjects: subjects.map((s) => s.trim()) as [string, string, string, string, string],
      });
      return;
    }

    if (kind === "face") {
      if (frames.length < 3) {
        setValidationError("Capture the guided live sequence before running the face check.");
        return;
      }
      if (!consentSubject.trim()) {
        setValidationError("Name the person who consented to this face comparison.");
        return;
      }
      onSubmit({
        kind: "face",
        document: document[0],
        frames,
        consentSubject: consentSubject.trim(),
        challenge,
      });
    }
  }

  return (
    <form className="details-form" onSubmit={handleSubmit} data-anim="details-form">
      <div className="details-form__header">
        <button
          type="button"
          className="details-form__back"
          onClick={onBack}
          disabled={isUploading}
        >
          ← Change document type
        </button>
        <div className={`details-form__kind details-form__kind--${info.ceiling}`}>
          <span className="details-form__kind-label">{info.label}</span>
          <span className="details-form__kind-ceiling">{info.ceilingNote}</span>
        </div>
      </div>

      {isChecking ? (
        <CheckingStatus
          kind={kind}
          progress={phase.status === "uploading" ? phase.progress : 1}
          file={document[0] ?? null}
        />
      ) : (
        <div className="details-form__fields" data-anim="details-form-fields">
          <FileDrop
            label={kind === "aadhaar" || kind === "aadhaar-full" ? "Aadhaar front image" : kind === "face" ? "Reference ID portrait" : "Document image"}
            hint={kind === "face" ? "Use a clear, front-facing image of the ID portrait. Image files only." : "Image (JPEG/PNG) or PDF."}
            accept={kind === "face" ? "image/*" : "image/*,application/pdf"}
            files={document}
            onChange={setDocument}
            required
          />

          {document[0] && kind !== "face" && <ScanPreview file={document[0]} stepLabel="Document preview · first page" processing={false} />}
          {(kind === "aadhaar" || kind === "aadhaar-full") && (
            <FileDrop
              label="Aadhaar back image (QR side)"
              hint="Optional for legacy single-sided cards; required for full QR verification on new-format cards."
              accept="image/*,application/pdf"
              files={backDocument}
              onChange={setBackDocument}
            />
          )}

          {kind === "aadhaar-full" && (
            <>
              <FaceCapture
                challenge={challenge}
                onChallengeChange={setChallenge}
                frames={frames}
                onFramesChange={setFrames}
              />
              <div className="text-field">
                <label htmlFor="consent-subject">Consent subject</label>
                <p className="text-field__hint">
                  Name of the person who consented to this face/ID check being run (must be on
                  the server's consent list).
                </p>
                <input
                  id="consent-subject"
                  type="text"
                  value={consentSubject}
                  onChange={(e) => setConsentSubject(e.target.value)}
                  placeholder="e.g. priya"
                />
              </div>
            </>
          )}

          {kind === "face" && (
            <>
              <FaceCapture
                challenge={challenge}
                onChallengeChange={setChallenge}
                frames={frames}
                onFramesChange={setFrames}
              />
              <div className="text-field consent-field">
                <label htmlFor="face-consent-subject">Consent record</label>
                <p className="text-field__hint">
                  Enter the subject identifier configured by the operator. Submitting confirms that this person agreed to the comparison.
                </p>
                <input
                  id="face-consent-subject"
                  type="text"
                  value={consentSubject}
                  onChange={(event) => setConsentSubject(event.target.value)}
                  placeholder="Consenting subject"
                  autoComplete="off"
                />
              </div>
            </>
          )}

          {kind === "marksheet" && (
            <div className="subjects-field">
              <p className="subjects-field__label">Five subjects to include in the total</p>
              <div className="subjects-field__grid">
                {subjects.map((value, index) => (
                  <input
                    key={index}
                    type="text"
                    value={value}
                    placeholder={`Subject ${index + 1}`}
                    onChange={(e) => {
                      const next = [...subjects];
                      next[index] = e.target.value;
                      setSubjects(next);
                    }}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {validationError ? (
        <p className="form-validation-error" role="alert">
          {validationError}
        </p>
      ) : null}

      {phase.status === "error" && <ErrorPanel error={new ApiError(phase.httpStatus, phase.detail)} />}

      {!isChecking && (
        <button type="submit" className="button button--primary">
          {kind === "face" ? "Compare face" : "Run check"}
        </button>
      )}
    </form>
  );
}
