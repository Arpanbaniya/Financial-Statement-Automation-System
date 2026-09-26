"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as tus from "tus-js-client";
import { createClient } from "../../lib/supabase/client";

type DocumentRow = {
  id: string;
  original_filename: string;
  file_size: number;
  status: string;
  created_at: string;
};

type Reservation = {
  document_id: string;
  storage_path: string;
  status: "reserved";
};

const MAX_BYTES = 10 * 1024 * 1024;
const BUCKET = "financial-documents";
const MIME_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  csv: "text/csv",
};
const CSV_MIMES = [
  "text/csv",
  "application/csv",
  "application/vnd.ms-excel",
  "",
];

function fileType(file: File): string {
  const extension = file.name.split(".").at(-1)?.toLowerCase() || "";
  const expected = MIME_BY_EXTENSION[extension];
  if (!expected) throw new Error("Choose a PDF, XLSX, or CSV file.");
  if (
    extension === "csv"
      ? !CSV_MIMES.includes(file.type)
      : file.type !== expected
  ) {
    throw new Error("The file type does not match its extension.");
  }
  return expected;
}

async function validateFile(file: File): Promise<string> {
  if (
    !file.name ||
    file.name.length > 255 ||
    /[\\/\x00-\x1f\x7f]/.test(file.name)
  ) {
    throw new Error("The filename is invalid.");
  }
  if (file.size < 1 || file.size > MAX_BYTES) {
    throw new Error("The file must be between 1 byte and 10 MB.");
  }
  const mime = fileType(file);
  const bytes = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  if (
    mime === "application/pdf" &&
    new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-"
  ) {
    throw new Error("This file does not look like a PDF.");
  }
  if (
    mime.includes("spreadsheetml") &&
    !(bytes[0] === 0x50 && bytes[1] === 0x4b)
  ) {
    throw new Error("This file does not look like an XLSX workbook.");
  }
  if (mime === "text/csv" && bytes.includes(0)) {
    throw new Error("This file does not look like a text CSV.");
  }
  return mime;
}

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  return "The request failed. Please try again.";
}

async function request<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw new Error(errorMessage(data.detail));
  return data as T;
}

async function accessToken(): Promise<string> {
  const { data, error } = await createClient().auth.getSession();
  if (error || !data.session)
    throw new Error("Your session expired. Please sign in again.");
  return data.session.access_token;
}

export function DocumentUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [phase, setPhase] = useState("Ready to upload");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const uploadRef = useRef<tus.Upload | null>(null);

  const refresh = useCallback(async () => {
    const token = await accessToken();
    setRows(await request<DocumentRow[]>("/api/documents", token));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh().catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Could not load documents.",
        ),
      );
    }, 0);
    return () => {
      window.clearTimeout(timer);
      void uploadRef.current?.abort();
    };
  }, [refresh]);

  async function submit() {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setProgress(0);
    try {
      setPhase("Checking file");
      const mime = await validateFile(file);
      setPhase("Calculating file fingerprint");
      const hash = await sha256(file);
      const token = await accessToken();
      setPhase("Reserving private storage");
      const reservation = await request<Reservation>("/api/documents", token, {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          mime_type: mime,
          file_size: file.size,
          sha256: hash,
        }),
      });

      const finish = async () => {
        setPhase("Verifying upload");
        const freshToken = await accessToken();
        await request(
          `/api/documents/${reservation.document_id}/complete`,
          freshToken,
          { method: "POST" },
        );
        setPhase("Uploaded. Processing will be added next.");
        setProgress(100);
        setFile(null);
        await refresh();
      };

      const projectUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
      const storageUrl = projectUrl.replace(
        ".supabase.co",
        ".storage.supabase.co",
      );
      setPhase("Uploading directly to private storage");
      await new Promise<void>((resolve, reject) => {
        const upload = new tus.Upload(file, {
          endpoint: `${storageUrl}/storage/v1/upload/resumable`,
          headers: { authorization: `Bearer ${token}` },
          metadata: {
            bucketName: BUCKET,
            objectName: reservation.storage_path,
            contentType: mime,
            cacheControl: "3600",
          },
          chunkSize: 6 * 1024 * 1024,
          uploadDataDuringCreation: true,
          removeFingerprintOnSuccess: true,
          retryDelays: [0, 1000, 3000, 5000],
          fingerprint: () =>
            Promise.resolve(`${reservation.storage_path}:${hash}`),
          onProgress: (sent, total) =>
            setProgress(Math.round((sent / total) * 100)),
          onError: (cause) => {
            if (
              "originalResponse" in cause &&
              cause.originalResponse?.getStatus() === 409
            ) {
              resolve(); // A previous attempt may have completed; the API checks the object.
            } else {
              reject(cause);
            }
          },
          onSuccess: () => resolve(),
        });
        uploadRef.current = upload;
        upload
          .findPreviousUploads()
          .then((previous) => {
            if (previous.length) upload.resumeFromPreviousUpload(previous[0]);
            upload.start();
          })
          .catch(reject);
      });
      uploadRef.current = null;
      await finish();
    } catch (cause) {
      setPhase("Upload needs attention");
      setError(
        cause instanceof Error
          ? cause.message
          : "The upload failed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="upload-panel" aria-labelledby="upload-heading">
      <h2 id="upload-heading">Your documents</h2>
      <p>
        Upload one PDF, XLSX, or CSV file at a time, up to 10 MB. Files are
        private to your account.
      </p>
      <label className="upload-label" htmlFor="document-file">
        Choose a financial statement
      </label>
      <input
        id="document-file"
        type="file"
        accept=".pdf,.xlsx,.csv,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
        disabled={busy}
        onChange={(event) => {
          setFile(event.target.files?.[0] || null);
          setError("");
          setProgress(0);
        }}
      />
      <button
        className="button button--primary"
        type="button"
        disabled={!file || busy}
        onClick={submit}
      >
        {busy ? "Uploading…" : "Upload document"}
      </button>
      <p className="upload-status" role="status">
        {phase}
        {busy ? ` · ${progress}%` : ""}
      </p>
      {busy && (
        <progress max={100} value={progress} aria-label="Upload progress" />
      )}
      {error && (
        <p className="form-message form-message--error" role="alert">
          {error}
        </p>
      )}
      <h3>Recent uploads</h3>
      {rows.length === 0 ? (
        <p>No documents yet.</p>
      ) : (
        <ul className="document-list">
          {rows.map((row) => (
            <li key={row.id}>
              <span>{row.original_filename}</span>
              <small>
                {(row.file_size / 1024).toFixed(0)} KB ·{" "}
                {row.status.replaceAll("_", " ")}
              </small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
