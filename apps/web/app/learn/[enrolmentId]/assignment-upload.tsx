"use client";

import { useState } from "react";

import { getAccessToken } from "@/lib/session";

interface SubmissionResponse {
  id: string;
  version: number;
  approved_at: string | null;
  rejected_reason: string | null;
}

/**
 * Assignment submission (02 §7.7, REQ-BYPASS-08). The file is
 * virus-scanned server-side before it is ever stored — a rejection here
 * means the scanner refused it, not a generic upload failure.
 */
export function AssignmentUpload({ assignmentId }: { assignmentId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<SubmissionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const token = getAccessToken();
    const body = new FormData();
    body.append("file", file);
    const resp = await fetch(`/api/bff/assignments/${assignmentId}/submissions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
    });
    setBusy(false);
    if (!resp.ok) {
      const payload = await resp.json().catch(() => null);
      setError(
        payload?.error?.details?.signature
          ? "That file was rejected by the virus scanner."
          : "Could not submit this file."
      );
      return;
    }
    setResult(await resp.json());
  }

  if (result) {
    return (
      <div className="card mt-3">
        <p style={{ fontSize: "0.875rem" }}>Submitted (version {result.version}).</p>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          {result.approved_at
            ? "Approved."
            : result.rejected_reason
              ? `Rejected: ${result.rejected_reason}`
              : "Awaiting facilitator review."}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="card mt-3 flex flex-col gap-3">
      <input
        type="file"
        aria-label="Assignment file"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        style={{ fontSize: "0.8125rem" }}
      />
      {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
      <button
        type="submit"
        disabled={busy || !file}
        className="btn btn--primary"
        style={{ alignSelf: "flex-start" }}
      >
        Submit assignment
      </button>
    </form>
  );
}
