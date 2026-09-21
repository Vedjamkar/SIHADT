import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import {
  addStoredDocuments,
  listStoredDocuments,
  removeStoredDocument,
  updateDocumentCategory,
} from "../lib/documentStore";
import type { DocumentCategory, StoredDocument } from "../lib/documentStore";
import type { DocumentKind } from "../types/api";

const CATEGORIES: Array<{ id: DocumentCategory; label: string; description: string }> = [
  { id: "identity", label: "Identity", description: "IDs, Aadhaar, PAN and passports" },
  { id: "education", label: "Education", description: "Marksheets, degrees and certificates" },
  { id: "financial", label: "Financial", description: "Statements, receipts and tax files" },
  { id: "medical", label: "Medical", description: "Reports, prescriptions and health records" },
  { id: "legal", label: "Legal", description: "Contracts, deeds and agreements" },
  { id: "other", label: "Other", description: "Files that need your review" },
];

type CategoryFilter = "all" | DocumentCategory;
type SortOrder = "newest" | "name" | "size";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(timestamp: number) {
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(timestamp);
}

function fileKind(document: StoredDocument) {
  if (document.mimeType === "application/pdf" || document.name.toLowerCase().endsWith(".pdf")) return "PDF";
  if (document.mimeType.startsWith("image/")) return "Image";
  return document.name.split(".").pop()?.toUpperCase() || "File";
}

export interface OrganizerVerificationSelection {
  id: string;
  kind: DocumentKind;
  document: File;
  backDocument?: File;
}

interface OrganizerViewProps {
  onVerifyAgain: (selection: OrganizerVerificationSelection) => void;
}

const KIND_LABELS: Partial<Record<DocumentKind, string>> = {
  aadhaar: "Aadhaar",
  "aadhaar-full": "Aadhaar with identity binding",
  pan: "PAN",
  passport: "Passport",
  marksheet: "Marksheet",
};

function asFile(document: StoredDocument) {
  return new File([document.file], document.name, {
    type: document.mimeType,
    lastModified: document.lastModified,
  });
}

export function OrganizerView({ onVerifyAgain }: OrganizerViewProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [filter, setFilter] = useState<CategoryFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortOrder>("newest");
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [storageUsed, setStorageUsed] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    listStoredDocuments()
      .then((items) => active && setDocuments(items))
      .catch(() => active && setMessage("This browser could not open local document storage."))
      .finally(() => active && setLoading(false));
    refreshStorageEstimate();
    return () => { active = false; };
  }, []);

  async function refreshStorageEstimate() {
    if (!navigator.storage?.estimate) return;
    const estimate = await navigator.storage.estimate();
    setStorageUsed(estimate.usage ?? null);
  }

  async function importFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    const files = Array.from(fileList).filter((file) => file.size > 0);
    if (!files.length) {
      setMessage("Choose at least one non-empty file.");
      return;
    }
    try {
      const added = await addStoredDocuments(files);
      setDocuments((current) => [...current, ...added]);
      setMessage(`${added.length} ${added.length === 1 ? "file" : "files"} added and classified.`);
      await refreshStorageEstimate();
    } catch {
      setMessage("The files could not be saved. Your browser storage may be full or unavailable.");
    }
  }

  async function changeCategory(id: string, category: DocumentCategory) {
    setDocuments((current) => current.map((item) => item.id === id ? { ...item, category } : item));
    try {
      await updateDocumentCategory(id, category);
    } catch {
      setMessage("That category change could not be saved.");
      setDocuments(await listStoredDocuments());
    }
  }

  async function deleteDocument(document: StoredDocument) {
    if (!window.confirm(`Remove “${document.name}” from this device? This cannot be undone.`)) return;
    try {
      await removeStoredDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setMessage(`${document.name} was removed.`);
      await refreshStorageEstimate();
    } catch {
      setMessage("The file could not be removed.");
    }
  }

  function openDocument(document: StoredDocument) {
    const url = URL.createObjectURL(document.file);
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (!opened) setMessage("Allow pop-ups to preview this file.");
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  function downloadDocument(document: StoredDocument) {
    const url = URL.createObjectURL(document.file);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document.name;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  const counts = useMemo(() => Object.fromEntries(CATEGORIES.map(({ id }) => [
    id,
    documents.filter((document) => document.category === id).length,
  ])) as Record<DocumentCategory, number>, [documents]);

  const visibleDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return documents
      .filter((document) => filter === "all" || document.category === filter)
      .filter((document) => !normalizedQuery || [
        document.name,
        document.verificationKind,
        document.verdict,
        document.verificationRecordId,
      ].some((value) => value?.toLocaleLowerCase().includes(normalizedQuery)))
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name);
        if (sort === "size") return b.size - a.size;
        return b.addedAt - a.addedAt;
      });
  }, [documents, filter, query, sort]);

  const activeCategory = filter === "all" ? null : CATEGORIES.find((category) => category.id === filter);

  function verifyAgain(document: StoredDocument) {
    if (!document.verificationKind || document.verificationRole === "back") return;
    const relatedBack = documents.find((candidate) =>
      candidate.verificationRecordId === document.verificationRecordId
      && candidate.verificationRole === "back",
    );
    onVerifyAgain({
      id: document.id,
      kind: document.verificationKind,
      document: asFile(document),
      backDocument: relatedBack ? asFile(relatedBack) : undefined,
    });
  }

  return (
    <div className="organizer">
      <header className="organizer__header">
        <div>
          <p className="organizer__eyebrow">Private document library</p>
          <h1>Keep important files in order.</h1>
          <p>Documents used for a check are filed here automatically with their latest verification reference and outcome.</p>
        </div>
        <button type="button" className="button button--primary" onClick={() => inputRef.current?.click()}>
          Add documents
        </button>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          multiple
          accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx,.txt"
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            void importFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </header>

      <div className="organizer__privacy" role="note">
        <span aria-hidden="true">●</span>
        <div><strong>On-device storage</strong><small>Only a check you start is uploaded. Live face captures are never saved.</small></div>
        {storageUsed !== null && <span className="organizer__storage">Browser storage used: {formatBytes(storageUsed)}</span>}
      </div>

      <div className="organizer__layout">
        <aside className="organizer__folders" aria-label="Document folders">
          <button type="button" className={filter === "all" ? "is-active" : ""} onClick={() => setFilter("all")}>
            <span>All documents</span><b>{documents.length}</b>
          </button>
          {CATEGORIES.map((category) => (
            <button key={category.id} type="button" className={filter === category.id ? "is-active" : ""} onClick={() => setFilter(category.id)}>
              <span>{category.label}</span><b>{counts[category.id]}</b>
            </button>
          ))}
        </aside>

        <section className="organizer__content" aria-labelledby="organizer-list-title">
          <div className="organizer__toolbar">
            <div>
              <h2 id="organizer-list-title">{activeCategory?.label ?? "All documents"}</h2>
              <p>{activeCategory?.description ?? `${documents.length} files across ${CATEGORIES.filter((category) => counts[category.id] > 0).length} folders`}</p>
            </div>
            <div className="organizer__controls">
              <label>
                <span className="visually-hidden">Search documents</span>
                <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" />
              </label>
              <label>
                <span className="visually-hidden">Sort documents</span>
                <select value={sort} onChange={(event) => setSort(event.target.value as SortOrder)}>
                  <option value="newest">Newest first</option>
                  <option value="name">Name</option>
                  <option value="size">Largest first</option>
                </select>
              </label>
            </div>
          </div>

          <div
            className={`organizer__drop${dragging ? " is-dragging" : ""}`}
            onDragOver={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event: DragEvent<HTMLDivElement>) => {
              event.preventDefault();
              setDragging(false);
              void importFiles(event.dataTransfer.files);
            }}
          >
            <span aria-hidden="true">＋</span>
            <p>Drop documents anywhere here to classify and store them</p>
          </div>

          {message && <p className="organizer__message" role="status">{message}<button type="button" onClick={() => setMessage(null)} aria-label="Dismiss message">×</button></p>}

          {loading ? (
            <p className="organizer__empty">Opening your document library…</p>
          ) : visibleDocuments.length === 0 ? (
            <div className="organizer__empty">
              <div aria-hidden="true">▤</div>
              <h3>{documents.length ? "No matching files" : "Your library is ready"}</h3>
              <p>{documents.length ? "Try another folder or search term." : "Add PDFs, images, and office documents. They will be sorted into folders automatically."}</p>
              {!documents.length && <button type="button" className="button button--primary" onClick={() => inputRef.current?.click()}>Choose files</button>}
            </div>
          ) : (
            <ul className="organizer__files">
              {visibleDocuments.map((document) => (
                <li key={document.id} className="organizer-file">
                  <button type="button" className="organizer-file__preview" onClick={() => openDocument(document)} aria-label={`Open ${document.name}`}>
                    <span className={`organizer-file__icon organizer-file__icon--${document.category}`} aria-hidden="true">{fileKind(document)}</span>
                    <span className="organizer-file__title">
                      <span className="organizer-file__name">{document.name}</span>
                      {document.verificationKind && (
                        <small>
                          {document.verificationRole === "back" ? "Back side · " : ""}
                          {KIND_LABELS[document.verificationKind] ?? "Document check"}
                          {document.verdict ? ` · ${document.verdict.replaceAll("_", " ").toLocaleLowerCase()}` : " · saved from check"}
                          {document.verificationRecordId ? ` · Ref ${document.verificationRecordId.slice(0, 8)}` : ""}
                        </small>
                      )}
                    </span>
                  </button>
                  <span className="organizer-file__meta">{formatBytes(document.size)} · Added {formatDate(document.addedAt)}</span>
                  <label className="organizer-file__category">
                    <span className="visually-hidden">Folder for {document.name}</span>
                    <select value={document.category} onChange={(event) => void changeCategory(document.id, event.target.value as DocumentCategory)}>
                      {CATEGORIES.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
                    </select>
                  </label>
                  <div className="organizer-file__actions">
                    {document.verificationKind && document.verificationRole !== "back" && (
                      <button type="button" className="is-primary" onClick={() => verifyAgain(document)}>Verify again</button>
                    )}
                    <button type="button" onClick={() => openDocument(document)}>Open</button>
                    <button type="button" onClick={() => downloadDocument(document)}>Download</button>
                    <button type="button" className="is-danger" onClick={() => void deleteDocument(document)}>Remove</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
