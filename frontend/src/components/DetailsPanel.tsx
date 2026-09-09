import { useState } from "react";
import type { VerifyDetails } from "../types/api";

interface DetailsPanelProps {
  details: VerifyDetails;
}

/**
 * Raw per-check details (QR fields, ELA stats, OCR output, face similarity
 * scores, etc.) — available for anyone who wants to dig in, but collapsed
 * by default so it never competes with the verdict/reasons for attention.
 */
export function DetailsPanel({ details }: DetailsPanelProps) {
  const keys = Object.keys(details);
  if (keys.length === 0) return null;

  const maps = extractMaps(details);

  return (
    <>
    {maps.length ? <ForensicMapViewer maps={maps} /> : null}
    <details className="details-panel" data-anim="details-panel">
      <summary className="details-panel-summary">Raw check details</summary>
      <dl className="details-panel-list">
        {keys.map((key) => (
          <div className="details-panel-row" key={key}>
            <dt className="details-panel-key">{key}</dt>
            <dd className="details-panel-value">{renderValue(details[key])}</dd>
          </div>
        ))}
      </dl>
    </details>
    </>
  );
}

interface MapArtifact {
  id: string;
  label: string;
  description: string;
  alt: string;
  base64: string;
}

function extractMaps(details: VerifyDetails): MapArtifact[] {
  const artifacts: MapArtifact[] = [];
  const rendered = details.maps && typeof details.maps === "object"
    ? details.maps as Record<string, unknown>
    : null;
  const candidates = [
    {
      id: "noise",
      key: "noise_map_png_base64",
      label: "Noise field",
      description: "Local high-frequency variation measured across the uploaded pixels.",
      alt: "Server-generated map of local image noise",
    },
    {
      id: "spectrum",
      key: "spectrum_png_base64",
      label: "Frequency spectrum",
      description: "Periodic structure measured in the document image's frequency domain.",
      alt: "Server-generated image frequency spectrum",
    },
  ];
  for (const candidate of candidates) {
    const value = rendered?.[candidate.key];
    if (typeof value === "string" && value) artifacts.push({ ...candidate, base64: value });
  }

  const ela = details["ela"];
  if (ela && typeof ela === "object" && "heatmap_png_base64" in ela) {
    const value = (ela as Record<string, unknown>)["heatmap_png_base64"];
    if (typeof value === "string" && value) {
      artifacts.push({
        id: "ela",
        label: "Compression residual",
        description: "Error-level residual from a controlled JPEG re-save. Applicable only to some image histories.",
        alt: "Server-generated Error Level Analysis residual map",
        base64: value,
      });
    }
  }
  return artifacts;
}

function ForensicMapViewer({ maps }: { maps: MapArtifact[] }) {
  const [activeId, setActiveId] = useState(maps[0].id);
  const active = maps.find((map) => map.id === activeId) ?? maps[0];

  return (
    <section className="forensic-maps" aria-labelledby="forensic-maps-title">
      <div className="forensic-maps__heading">
        <div>
          <h3 id="forensic-maps-title">Image analysis</h3>
        </div>
        <span>{maps.length} channel{maps.length === 1 ? "" : "s"}</span>
      </div>
      <div className="forensic-maps__tabs" role="group" aria-label="Forensic map channel">
        {maps.map((map) => (
          <button
            key={map.id}
            type="button"
            aria-pressed={active.id === map.id}
            onClick={() => setActiveId(map.id)}
          >
            {map.label}
          </button>
        ))}
      </div>
      <figure className="forensic-maps__plate">
        <img src={`data:image/png;base64,${active.base64}`} alt={active.alt} />
        <figcaption>
          <strong>{active.label}.</strong> {active.description} Advisory evidence only; interpret it with the written reasons above.
        </figcaption>
      </figure>
    </section>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") {
    return truncateLongString(value);
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(sanitize(value), null, 2);
  } catch {
    return String(value);
  }
}

function truncateLongString(value: string): string {
  // Base64 image blobs (e.g. ELA heatmaps) are long and not useful as text.
  return value.length > 200 ? `${value.slice(0, 60)}… (${value.length} chars)` : value;
}

/** Recursively truncate long strings so nested base64 blobs never flood the DOM. */
function sanitize(value: unknown): unknown {
  if (typeof value === "string") return truncateLongString(value);
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, sanitize(v)]),
    );
  }
  return value;
}
