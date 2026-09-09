import { useEffect, useId, useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import { animateUploadState } from "../motion";

interface FileDropProps {
  label: string;
  hint?: string;
  accept?: string;
  multiple?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
  required?: boolean;
  disabled?: boolean;
}

/**
 * A single drag/drop-or-click file picker, used for every document, back
 * image, and frame-set upload in the app. Uses the design system's
 * `.upload-zone` contract (see styles/components.css) so its states
 * (idle/dragging/done/error) share the same visual language as the rest
 * of the app rather than looking like a generic HTML file input.
 */
export function FileDrop({
  label,
  hint,
  accept,
  multiple = false,
  files,
  onChange,
  required = false,
  disabled = false,
}: FileDropProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const zoneRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isDragging) animateUploadState(zoneRef.current, "dragging");
    else if (files.length > 0) animateUploadState(zoneRef.current, "done");
    else animateUploadState(zoneRef.current, "idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDragging]);

  function handleFiles(fileList: FileList | null) {
    if (!fileList) return;
    const next = Array.from(fileList);
    const allowed = (accept ?? "").split(",").map(type => type.trim());
    if (next.some(file => file.size === 0 || (allowed.length && allowed[0] && !allowed.some(type =>
      type.endsWith("/*") ? file.type.startsWith(type.slice(0, -1)) : type === file.type)))) {
      setError("Choose a non-empty file in one of the supported formats.");
      return;
    }
    setError(null);
    const merged = multiple ? [...files, ...next] : next.slice(0, 1);
    onChange(merged);
    animateUploadState(zoneRef.current, "done");
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    if (disabled) return;
    handleFiles(event.dataTransfer.files);
  }

  function removeFile(index: number) {
    onChange(files.filter((_, i) => i !== index));
  }

  const state = disabled ? "uploading" : isDragging ? "dragging" : files.length ? "done" : "idle";

  return (
    <div className="upload-field">
      <label className="upload-field__label" htmlFor={inputId}>
        {label}
        {required ? <span className="upload-field__required"> *</span> : null}
      </label>
      {hint ? <p className="upload-field__hint">{hint}</p> : null}
      <div
        ref={zoneRef}
        className={`upload-zone upload-zone--${state}`}
        data-anim="upload-zone"
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={`Choose ${label.toLowerCase()}`}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (!disabled) inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
          className="upload-zone__input"
        />
        <svg
          className="upload-zone__icon"
          data-anim="upload-icon"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4 15v2.5A2.5 2.5 0 0 0 6.5 20h11a2.5 2.5 0 0 0 2.5-2.5V15"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <p className="upload-zone__title">
          {files.length > 0 ? (multiple ? "Add another file" : "Replace file") : "Drop a file here"}
        </p>
        <p className="upload-zone__hint">or click to choose{multiple ? " one or more files" : ""}</p>
      </div>
      {error && <p className="form-validation-error" role="alert">{error}</p>}
      {files.length > 0 ? (
        <ul className="upload-field__list" data-anim="upload-field-list">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="upload-field__item">
              <span className="upload-field__item-name">{file.name}</span>
              <span className="upload-field__item-size">{(file.size / 1024).toFixed(0)} KB</span>
              {!disabled ? (
                <button
                  type="button"
                  className="upload-field__item-remove"
                  onClick={(event) => {
                    event.stopPropagation();
                    removeFile(index);
                  }}
                  aria-label={`Remove ${file.name}`}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
