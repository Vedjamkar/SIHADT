import { useEffect, useRef, useState } from "react";

export type FaceChallenge = "blink" | "head_turn";

interface FaceCaptureProps {
  challenge: FaceChallenge;
  onChallengeChange: (challenge: FaceChallenge) => void;
  frames: File[];
  onFramesChange: (frames: File[]) => void;
}

const FRAME_COUNT = 20;
const FRAME_INTERVAL_MS = 140;

/**
 * Short-lived, consent-led camera capture. Frames only exist as in-memory
 * File objects until the form is submitted; tracks are stopped after capture,
 * on cancel, and on unmount.
 */
export function FaceCapture({
  challenge,
  onChallengeChange,
  frames,
  onFramesChange,
}: FaceCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const generationRef = useRef(0);
  const [cameraState, setCameraState] = useState<"idle" | "starting" | "ready" | "capturing">("idle");
  const [captureIndex, setCaptureIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  function releaseCamera(cancelCapture = true) {
    if (cancelCapture) generationRef.current += 1;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraState("idle");
  }

  useEffect(() => () => {
    generationRef.current += 1;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  async function startCamera() {
    setError(null);
    setCameraState("starting");
    const generation = ++generationRef.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera capture is not supported in this browser.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
        audio: false,
      });
      if (generation !== generationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      if (generation !== generationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      setCameraState("ready");
    } catch (cause) {
      if (generation !== generationRef.current) return;
      releaseCamera();
      setError(cause instanceof Error ? cause.message : "The camera could not be opened.");
    }
  }

  async function captureSequence() {
    const video = videoRef.current;
    if (!video || !streamRef.current || video.videoWidth === 0) return;
    setError(null);
    setCameraState("capturing");
    setCaptureIndex(0);
    const generation = ++generationRef.current;

    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 720 / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) {
      setError("This browser could not prepare the camera frames.");
      setCameraState("ready");
      return;
    }

    const nextFrames: File[] = [];
    for (let index = 0; index < FRAME_COUNT; index += 1) {
      if (generation !== generationRef.current) return;
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
      if (generation !== generationRef.current) return;
      if (blob) nextFrames.push(new File([blob], `live-frame-${index + 1}.jpg`, { type: "image/jpeg" }));
      setCaptureIndex(index + 1);
      if (index < FRAME_COUNT - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, FRAME_INTERVAL_MS));
      }
    }

    if (generation !== generationRef.current) return;
    releaseCamera(false);
    if (nextFrames.length < 3) {
      onFramesChange([]);
      setError("Too few frames were captured. Please try the sequence again.");
      return;
    }
    onFramesChange(nextFrames);
  }

  const instruction = challenge === "blink"
    ? "Keep your face inside the oval and blink naturally once while the ticks fill."
    : "Keep your shoulders still and turn your head slowly left, then back to centre.";

  return (
    <section className="face-capture" aria-labelledby="live-capture-title">
      <div className="face-capture__heading">
        <div>
          <h3 id="live-capture-title">Live camera capture</h3>
        </div>
        <span className="face-capture__privacy">In memory · discarded after request</span>
      </div>

      <fieldset className="challenge-picker" disabled={cameraState === "capturing"}>
        <legend>Choose a liveness prompt</legend>
        <label>
          <input
            type="radio"
            name="face-challenge"
            checked={challenge === "blink"}
            onChange={() => {
              onFramesChange([]);
              onChallengeChange("blink");
            }}
          />
          <span><strong>Blink once</strong><small>Best when the camera is steady</small></span>
        </label>
        <label>
          <input
            type="radio"
            name="face-challenge"
            checked={challenge === "head_turn"}
            onChange={() => {
              onFramesChange([]);
              onChallengeChange("head_turn");
            }}
          />
          <span><strong>Turn your head</strong><small>Useful if blinking is difficult</small></span>
        </label>
      </fieldset>

      <div className={`camera-stage camera-stage--${cameraState}`}>
        <video ref={videoRef} muted playsInline aria-label="Live camera preview" />
        {cameraState === "idle" && frames.length === 0 ? (
          <div className="camera-stage__empty">
            <span aria-hidden="true">◎</span>
            <p>The camera starts only when you ask.</p>
          </div>
        ) : null}
        {frames.length > 0 && cameraState === "idle" ? (
          <div className="camera-stage__complete">
            <strong>Sequence captured</strong>
            <p>{frames.length} in-memory frames are ready.</p>
          </div>
        ) : null}
        {(cameraState === "ready" || cameraState === "capturing") && (
          <div className="camera-stage__guide" aria-hidden="true"><span /></div>
        )}
        {cameraState === "capturing" && (
          <div className="camera-stage__ticks" aria-hidden="true">
            {Array.from({ length: FRAME_COUNT }, (_, index) => (
              <span key={index} className={index < captureIndex ? "is-filled" : ""} />
            ))}
          </div>
        )}
      </div>

      <p className="face-capture__instruction" aria-live="polite">
        {cameraState === "capturing" ? instruction : frames.length ? "Review complete. Retake if the movement was unclear." : instruction}
      </p>
      {error ? <p className="form-validation-error" role="alert">{error}</p> : null}

      <div className="face-capture__actions">
        {cameraState === "idle" ? (
          <button type="button" className="button button--secondary" onClick={startCamera}>
            {frames.length ? "Retake sequence" : "Open camera"}
          </button>
        ) : null}
        {cameraState === "starting" ? <button type="button" className="button button--secondary" disabled>Opening camera…</button> : null}
        {cameraState === "ready" ? (
          <button type="button" className="button button--primary" onClick={captureSequence}>Begin 3-second capture</button>
        ) : null}
        {(cameraState === "starting" || cameraState === "ready" || cameraState === "capturing") ? (
          <button type="button" className="button button--ghost" onClick={() => releaseCamera()}>Cancel camera</button>
        ) : null}
      </div>

      <aside className="capability-note">
        <span className="capability-note__state">Unavailable</span>
        <p><strong>Deepfake and screen-replay detection</strong> is not implemented by this system. The check measures a blink or head turn and face similarity; it must not be read as presentation-attack detection.</p>
      </aside>
    </section>
  );
}
