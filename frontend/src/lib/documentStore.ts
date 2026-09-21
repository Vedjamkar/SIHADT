import type { DocumentKind, IdentityBinding, Verdict, VerifyResponse } from "../types/api";

export type DocumentCategory = "identity" | "education" | "financial" | "medical" | "legal" | "other";
export type VerificationFileRole = "primary" | "back";

export interface StoredDocument {
  id: string;
  name: string;
  category: DocumentCategory;
  mimeType: string;
  size: number;
  addedAt: number;
  lastModified: number;
  file: Blob;
  verificationKind?: DocumentKind;
  verificationRole?: VerificationFileRole;
  verificationRecordId?: string;
  verdict?: Verdict;
  identityBinding?: IdentityBinding;
  verifiedAt?: number;
}

const DATABASE_NAME = "verifai-document-organizer";
const DATABASE_VERSION = 1;
const STORE_NAME = "documents";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onerror = () => reject(request.error ?? new Error("Could not open local document storage."));
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("addedAt", "addedAt");
        store.createIndex("category", "category");
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Local document storage failed."));
  });
}

export async function listStoredDocuments(): Promise<StoredDocument[]> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readonly");
    return await requestResult(transaction.objectStore(STORE_NAME).getAll());
  } finally {
    database.close();
  }
}

export async function addStoredDocuments(files: File[]): Promise<StoredDocument[]> {
  const database = await openDatabase();
  const addedAt = Date.now();
  const documents = files.map((file, index): StoredDocument => ({
    id: crypto.randomUUID(),
    name: file.name,
    category: classifyDocument(file),
    mimeType: file.type || "application/octet-stream",
    size: file.size,
    addedAt: addedAt + index,
    lastModified: file.lastModified,
    file,
  }));

  try {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    await Promise.all(documents.map((document) => requestResult(store.add(document))));
    return documents;
  } finally {
    database.close();
  }
}

export async function storeVerificationDocuments(
  kind: DocumentKind,
  files: Array<{ file: File; role: VerificationFileRole }>,
  result?: VerifyResponse,
): Promise<StoredDocument[]> {
  if (kind === "face") return [];

  const existing = await listStoredDocuments();
  const usedIds = new Set<string>();
  const now = Date.now();
  const documents = files.map(({ file, role }, index): StoredDocument => {
    const match = existing.find((document) =>
      !usedIds.has(document.id)
      && document.name === file.name
      && document.size === file.size
      && document.lastModified === file.lastModified,
    );
    if (match) usedIds.add(match.id);
    return {
      ...(match ?? {
        id: crypto.randomUUID(),
        name: file.name,
        category: classifyDocumentForVerification(kind),
        mimeType: file.type || "application/octet-stream",
        size: file.size,
        addedAt: now + index,
        lastModified: file.lastModified,
      }),
      file,
      category: match?.category ?? classifyDocumentForVerification(kind),
      verificationKind: kind,
      verificationRole: role,
      verificationRecordId: result?.record_id ?? match?.verificationRecordId,
      verdict: result?.verdict ?? match?.verdict,
      identityBinding: result?.identity_binding ?? match?.identityBinding,
      verifiedAt: result ? now : match?.verifiedAt,
    };
  });

  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    await Promise.all(documents.map((document) => requestResult(store.put(document))));
    return documents;
  } finally {
    database.close();
  }
}

export async function updateDocumentCategory(id: string, category: DocumentCategory): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const document = await requestResult<StoredDocument | undefined>(store.get(id));
    if (!document) throw new Error("Document no longer exists.");
    await requestResult(store.put({ ...document, category }));
  } finally {
    database.close();
  }
}

export async function removeStoredDocument(id: string): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    await requestResult(transaction.objectStore(STORE_NAME).delete(id));
  } finally {
    database.close();
  }
}

export function classifyDocument(file: File): DocumentCategory {
  const name = file.name.toLocaleLowerCase();
  const rules: Array<[DocumentCategory, RegExp]> = [
    ["identity", /aadhaar|aadhar|pan[\s_-]?card|passport|driv(?:ing|er)|licen[cs]e|voter|identity|\bid\b|ration/],
    ["education", /marksheet|mark[\s_-]?sheet|transcript|degree|diploma|school|college|university|certificate|result/],
    ["financial", /invoice|receipt|bank|statement|salary|payslip|tax|itr|gst|bill|payment/],
    ["medical", /medical|health|hospital|prescription|lab[\s_-]?report|vaccine|insurance/],
    ["legal", /agreement|contract|affidavit|deed|court|legal|lease|notary/],
  ];

  return rules.find(([, pattern]) => pattern.test(name))?.[0] ?? "other";
}

function classifyDocumentForVerification(kind: DocumentKind): DocumentCategory {
  return kind === "marksheet" ? "education" : "identity";
}
