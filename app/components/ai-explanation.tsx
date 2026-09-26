"use client";

import Link from "next/link";
import { useState } from "react";
import { createClient } from "../../lib/supabase/client";

type Fact = {
  id: string;
  kind: "metric" | "warning";
  label: string;
  value: string | null;
  unit: string | null;
  sources: { document_id: string; line_item_id: string }[];
};

type Result = {
  mode: "ai" | "facts_only";
  period_end: string;
  facts: Fact[];
  notes: { fact_id: string; text: string }[];
};

export function AiExplanation({
  companyId,
  focus,
  hasMetrics,
}: {
  companyId: string;
  focus: string;
  hasMetrics: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function explain() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    setResult(null);
    try {
      const { data, error } = await createClient().auth.getSession();
      if (error || !data.session)
        throw new Error("Your session expired. Sign in again.");
      const response = await fetch("/api/ai/explain", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${data.session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          company_id: companyId,
          focus: focus.replaceAll(" ", "_"),
        }),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok)
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : "Explanation could not be prepared.",
        );
      setResult(body as Result);
    } catch (cause) {
      setMessage(
        cause instanceof Error
          ? cause.message
          : "Explanation could not be prepared.",
      );
    } finally {
      setBusy(false);
    }
  }

  const facts = new Map(result?.facts.map((fact) => [fact.id, fact]));
  return (
    <section className="workspace-card">
      <h2>Explain these results</h2>
      <p>
        This sends calculated figures to Groq only when you press the button.
        Check the linked source values before relying on the explanation.
      </p>
      <button
        type="button"
        className="button button--secondary"
        onClick={explain}
        disabled={busy || !hasMetrics}
      >
        {busy ? "Preparing…" : "Explain"}
      </button>
      {!hasMetrics && <p>Accepted, source-linked results are needed first.</p>}
      {message && <p role="alert">{message}</p>}
      {result && (
        <div aria-live="polite">
          <p>
            {result.mode === "ai"
              ? "Optional AI explanation, with calculated facts below."
              : "Calculated facts are available. AI explanation is unavailable."}
          </p>
          {result.notes.map((note, index) => {
            const fact = facts.get(note.fact_id);
            return fact ? (
              <p key={`${note.fact_id}-${index}`}>
                <strong>{fact.label}:</strong> {note.text}
              </p>
            ) : null;
          })}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Calculated fact</th>
                  <th scope="col">Value</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {result.facts.map((fact) => (
                  <tr key={fact.id}>
                    <th scope="row">{fact.label}</th>
                    <td>
                      {fact.value === null
                        ? "Review warning"
                        : `${fact.value} ${fact.unit || ""}`}
                    </td>
                    <td>
                      {fact.sources.map((source, index) => (
                        <Link
                          key={`${source.document_id}-${source.line_item_id}`}
                          href={`/dashboard/documents/${source.document_id}#line-${source.line_item_id}`}
                        >
                          Source {index + 1}{" "}
                        </Link>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
