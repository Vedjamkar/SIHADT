/**
 * Discriminated union of what UploadView can submit. App.tsx pattern-matches
 * on `kind` to call the right api/client function — this is the seam
 * between the form (structure/interaction) and the network call (data flow).
 */
export type SubmitPayload =
  | { kind: "aadhaar"; document: File; backDocument: File | null }
  | {
      kind: "aadhaar-full";
      document: File;
      backDocument: File | null;
      frames: File[];
      consentSubject: string;
      challenge: "blink" | "head_turn";
    }
  | { kind: "pan"; document: File }
  | {
      kind: "marksheet";
      document: File;
      subjects: [string, string, string, string, string];
    }
  | {
      kind: "face";
      document: File;
      frames: File[];
      consentSubject: string;
      challenge: "blink" | "head_turn";
    };

export type UploadPhase =
  | { status: "idle" }
  | { status: "uploading"; progress: number }
  | { status: "error"; httpStatus: number; detail: string };
