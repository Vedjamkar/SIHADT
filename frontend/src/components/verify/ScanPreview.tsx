import { useCallback, useEffect, useRef, useState } from "react";
import { CornerBrackets } from "../CornerBrackets";
import { documentPreview } from "../../lib/documentPreview";

interface ScanPreviewProps {
  /** The document actually being checked. Nothing is drawn without one. */
  file: File | null;
  /** Index of the step currently running, for the caption. */
  stepLabel: string | null;
  /** True once the upload is done and the server is working. */
  processing: boolean;
}

/**
 * Shows the document being checked, with a sweep passing over it.
 *
 * Two deliberate honesty constraints, because this is the easiest place in
 * the whole app to accidentally lie:
 *
 *  1. The sweep is ILLUSTRATIVE, and is drawn as a moving band rather than
 *     as boxes around "detected regions". We do not get region coordinates
 *     back while a check is running — the API is one request/response — so
 *     drawing bounding boxes here would be inventing detections the system
 *     never made. A band that travels over the page says "working" without
 *     claiming to have found anything.
 *
 *  2. Real coordinates DO exist afterwards: ELA returns flagged blocks with
 *     x/y/w/h. Those are overlaid on the result view, where they are
 *     genuine. See ScanFindings.
 *
 * The preview is also just useful: it is the only place a user can confirm
 * the thing being checked is the thing they meant to upload.
 */
export function ScanPreview({ file, stepLabel, processing }: ScanPreviewProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [showMap, setShowMap] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setUrl(null);
    setPreviewError(null);
    setMapReady(false);
    if (file) documentPreview(file).then(blob => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    }).catch(error => {
      if (!cancelled) setPreviewError(error instanceof Error ? error.message : "Preview unavailable.");
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file]);

  const derivePreviewMap = useCallback((image: HTMLImageElement) => {
    const canvas = canvasRef.current;
    if (!canvas || !image.naturalWidth || !image.naturalHeight) return;

    const maximum = 720;
    const scale = Math.min(1, maximum / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    context.drawImage(image, 0, 0, width, height);

    const source = context.getImageData(0, 0, width, height);
    const output = context.createImageData(width, height);
    const luminance = new Float32Array(width * height);
    for (let index = 0; index < luminance.length; index += 1) {
      const offset = index * 4;
      luminance[index] = source.data[offset] * 0.299 + source.data[offset + 1] * 0.587 + source.data[offset + 2] * 0.114;
    }

    // Sobel magnitude: every coloured pixel is derived from a real brightness
    // transition in the selected image. This is a local preview, not a claim
    // that the backend has detected a manipulated region.
    for (let y = 1; y < height - 1; y += 1) {
      for (let x = 1; x < width - 1; x += 1) {
        const row = y * width;
        const gx =
          -luminance[row - width + x - 1] + luminance[row - width + x + 1]
          - 2 * luminance[row + x - 1] + 2 * luminance[row + x + 1]
          - luminance[row + width + x - 1] + luminance[row + width + x + 1];
        const gy =
          -luminance[row - width + x - 1] - 2 * luminance[row - width + x] - luminance[row - width + x + 1]
          + luminance[row + width + x - 1] + 2 * luminance[row + width + x] + luminance[row + width + x + 1];
        const signal = Math.min(1, Math.hypot(gx, gy) / 520);
        const intensity = Math.pow(signal, 0.72);
        const offset = (row + x) * 4;
        output.data[offset] = Math.round(232 + 20 * intensity);
        output.data[offset + 1] = Math.round(151 - 78 * intensity);
        output.data[offset + 2] = Math.round(45 - 20 * intensity);
        output.data[offset + 3] = Math.round(30 + 205 * intensity);
      }
    }
    context.putImageData(output, 0, 0);
    setMapReady(true);
  }, []);

  if (!url || previewError) {
    return (
      <div className="scan-preview scan-preview--empty">
        <div className="scan-preview__frame scan-preview__frame--placeholder bracket-frame">
          <CornerBrackets />
          <p className="scan-preview__placeholder">
            {previewError ?? (file ? "Preparing document preview…" : "No document loaded.")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <figure className="scan-preview" data-anim="scan-preview" data-processing={processing}>
      <div className="scan-preview__frame bracket-frame">
        <div className="scan-preview__specimen">
          <img
            className="scan-preview__image"
            src={url}
            alt="The document currently being checked"
            onLoad={(event) => derivePreviewMap(event.currentTarget)}
            onError={() => setPreviewError("This image could not be displayed.")}
          />
          <canvas
            ref={canvasRef}
            className={`scan-preview__analysis${mapReady ? " is-ready" : ""}`}
            style={showMap ? undefined : { visibility: "hidden" }}
            aria-hidden="true"
          />
          <div className="scan-preview__sweep" data-anim="scan-sweep" aria-hidden="true" />
        </div>
      </div>
      <figcaption className="scan-preview__caption">
        {processing && <button className="button button--ghost" type="button" aria-pressed={showMap} onClick={() => setShowMap(value => !value)}>
          {showMap ? "Show original" : "Show edge heatmap"}
        </button>}
        <span>{stepLabel ?? (processing ? "Waiting on the server" : "Ready")}</span>
        <span className="scan-preview__legend">
          <i aria-hidden="true" /> Browser edge preview · final forensic maps arrive with the server result
        </span>
      </figcaption>
    </figure>
  );
}

interface ScanFindingsProps {
  /** Real ELA block coordinates from the response, if any were flagged. */
  blocks: { x: number; y: number; w: number; h: number }[];
  /** Natural pixel size of the analysed image, for scaling the overlay. */
  width: number;
  height: number;
}

/**
 * Overlay of the regions ELA actually flagged.
 *
 * Unlike the sweep above, every rectangle here corresponds to a block the
 * backend really scored as anomalous — so it is safe to draw, and it is the
 * one genuinely forensic visual the system can produce.
 *
 * It is still only advisory: ELA fires readily on sharp printed text, and a
 * single flagged region cannot move the verdict by design. The caption says
 * so rather than leaving the picture to imply otherwise.
 */
export function ScanFindings({ blocks, width, height }: ScanFindingsProps) {
  if (!blocks.length || !width || !height) return null;

  return (
    <figure className="scan-findings">
      <svg
        className="scan-findings__svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${blocks.length} regions flagged by compression analysis`}
      >
        {blocks.map((b, i) => (
          <rect
            key={i}
            x={b.x}
            y={b.y}
            width={b.w}
            height={b.h}
            className="scan-findings__block"
          />
        ))}
      </svg>
      <figcaption className="scan-findings__caption">
        {blocks.length} region{blocks.length === 1 ? "" : "s"} flagged by compression
        analysis. Advisory only — this is common around printed text and cannot
        decide a verdict on its own.
      </figcaption>
    </figure>
  );
}
