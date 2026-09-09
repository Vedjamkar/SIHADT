import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

const previews = new WeakMap<File, Promise<Blob>>();

/** Render locally: document bytes never leave the browser for a preview. */
export function documentPreview(file: File): Promise<Blob> {
  const existing = previews.get(file);
  if (existing) return existing;
  const preview = render(file);
  previews.set(file, preview);
  preview.catch(() => previews.delete(file));
  return preview;
}

async function render(file: File): Promise<Blob> {
  const header = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer());
  if (header !== "%PDF-") return file;
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  const loading = pdfjs.getDocument({ data: await file.arrayBuffer() });
  try {
    const pdf = await loading.promise;
    const page = await pdf.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: Math.min(2, 1100 / Math.max(base.width, base.height)) });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    await page.render({ canvas, viewport }).promise;
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob =>
      blob ? resolve(blob) : reject(new Error("Preview could not be created.")), "image/png"));
  } catch (error) {
    if (error instanceof Error && error.name === "PasswordException") {
      throw new Error("This PDF is password-protected. Choose an unlocked copy to preview and scan it.");
    }
    throw new Error("This document could not be previewed. Try another PDF or image.");
  } finally {
    await loading.destroy();
  }
}
