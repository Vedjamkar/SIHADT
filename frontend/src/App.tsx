import { useEffect, useState } from "react";
import {
  ApiError,
  getHealth,
  getReasons,
  verifyAadhaar,
  verifyAadhaarFull,
  verifyMarksheet,
  verifyPan,
  verifyFace,
} from "./api/client";
import type { HealthResponse, VerifyResponse } from "./types/api";
import type { SubmitPayload, UploadPhase } from "./types/forms";
import { NavBar } from "./components/NavBar";
import type { View } from "./components/NavBar";
import { HealthBanner } from "./components/HealthBanner";
import { HomeView } from "./views/HomeView";
import { VerifyView } from "./views/VerifyView";
import { DashboardView } from "./components/DashboardView";

function App() {
  const [view, setView] = useState<View>("home");

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [reasonsDict, setReasonsDict] = useState<Record<string, string> | null>(null);

  const [uploadPhase, setUploadPhase] = useState<UploadPhase>({ status: "idle" });
  const [result, setResult] = useState<VerifyResponse | null>(null);

  // Fetched once at startup, per the brief: /reasons is used to translate
  // reason codes into sentences wherever the backend only sends a code
  // (dashboard's top_reasons and history rows do not carry `message`).
  useEffect(() => {
    getReasons()
      .then((response) => setReasonsDict(response.reasons))
      .catch(() => setReasonsDict(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      getHealth()
        .then((response) => {
          if (!cancelled) {
            setHealth(response);
            setHealthError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setHealthError(err instanceof ApiError ? err.detail : "Unknown error.");
          }
        });
    }
    poll();
    const interval = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  async function handleSubmit(payload: SubmitPayload) {
    setUploadPhase({ status: "uploading", progress: 0 });
    const onProgress = (fraction: number) => setUploadPhase({ status: "uploading", progress: fraction });

    try {
      let response: VerifyResponse;
      switch (payload.kind) {
        case "aadhaar":
          response = await verifyAadhaar(payload.document, payload.backDocument, onProgress);
          break;
        case "aadhaar-full":
          response = await verifyAadhaarFull(
            {
              document: payload.document,
              backDocument: payload.backDocument,
              frames: payload.frames,
              consentSubject: payload.consentSubject,
              challenge: payload.challenge,
            },
            onProgress,
          );
          break;
        case "pan":
          response = await verifyPan(payload.document, onProgress);
          break;
        case "marksheet":
          response = await verifyMarksheet(payload.document, payload.subjects, onProgress);
          break;
        case "face":
          response = await verifyFace(
            {
              idPhoto: payload.document,
              frames: payload.frames,
              consentSubject: payload.consentSubject,
              challenge: payload.challenge,
            },
            onProgress,
          );
          break;
      }
      setResult(response);
      setUploadPhase({ status: "idle" });
    } catch (err) {
      const apiError =
        err instanceof ApiError ? err : new ApiError(0, "Something went wrong while submitting this check.");
      setUploadPhase({ status: "error", httpStatus: apiError.status, detail: apiError.detail });
    }
  }

  function handleCheckAnother() {
    setResult(null);
    setUploadPhase({ status: "idle" });
  }

  function handleNavigate(nextView: View) {
    if (uploadPhase.status === "uploading") return;
    if (
      nextView !== view &&
      (view === "verify" || view === "face" || nextView === "verify" || nextView === "face")
    ) {
      setResult(null);
      setUploadPhase({ status: "idle" });
    }
    setView(nextView);
  }

  return (
    <div className="app-shell">
      <NavBar view={view} onNavigate={handleNavigate} locked={uploadPhase.status === "uploading"} />

      {view !== "home" && <HealthBanner health={health} error={healthError} />}

      <main className="app-main">
        {view === "home" && (
          <HomeView
            onStartCheck={() => handleNavigate("verify")}
            onStartFace={() => handleNavigate("face")}
            onViewDashboard={() => handleNavigate("dashboard")}
          />
        )}
        {view === "verify" && (
          <VerifyView
            phase={uploadPhase}
            result={result}
            onSubmit={handleSubmit}
            onCheckAnother={handleCheckAnother}
          />
        )}
        {view === "face" && (
          <VerifyView
            key="face-check"
            initialKind="face"
            phase={uploadPhase}
            result={result}
            onSubmit={handleSubmit}
            onCheckAnother={handleCheckAnother}
          />
        )}
        {view === "dashboard" && <DashboardView reasons={reasonsDict} />}
      </main>
    </div>
  );
}

export default App;
