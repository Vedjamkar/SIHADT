import { useState } from "react";
import type { DocumentKind } from "../types/api";
import type { SubmitPayload, UploadPhase } from "../types/forms";
import type { VerifyResponse } from "../types/api";
import { DocKindPicker } from "../components/verify/DocKindPicker";
import { DetailsForm } from "../components/verify/DetailsForm";
import { ResultView } from "../components/ResultView";

interface VerifyViewProps {
  phase: UploadPhase;
  result: VerifyResponse | null;
  onSubmit: (payload: SubmitPayload) => void;
  onCheckAnother: () => void;
  initialKind?: DocumentKind;
}

type Step = "choose" | "details";

/**
 * The guided verify flow: choose a document type, then see only the
 * fields that type needs, then a considered result reveal. Never all
 * seven-odd fields on one screen — one decision, then one focused form.
 * A returning user who already knows what they want reaches the upload
 * step in a single click, so this stays quick rather than a forced
 * multi-page wizard.
 */
export function VerifyView({ phase, result, onSubmit, onCheckAnother, initialKind }: VerifyViewProps) {
  const [step, setStep] = useState<Step>(initialKind ? "details" : "choose");
  const [kind, setKind] = useState<DocumentKind>(initialKind ?? "aadhaar");

  if (result) {
    return (
      <ResultView
        result={result}
        onCheckAnother={() => {
          onCheckAnother();
          setStep("choose");
        }}
      />
    );
  }

  if (step === "choose") {
    return (
      <DocKindPicker
        onSelect={(nextKind) => {
          setKind(nextKind);
          setStep("details");
        }}
      />
    );
  }

  return (
    <DetailsForm
      kind={kind}
      phase={phase}
      onBack={() => setStep("choose")}
      onSubmit={onSubmit}
    />
  );
}
