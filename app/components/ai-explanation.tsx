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
  provider: "groq" | "deterministic";
  fallback_used: boolean;
  text: string;
  period_end: string;
  facts: Fact[];
  notes: { fact_id: string; kind: "observation" | "question"; text: string }[];
};

export function AiExplanation({
  companyId,
  focus,
}: {
  companyId: string;
  focus: string;
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

  return (
    <section className="workspace-card">
      <h2>Explain these results</h2>
      <p>
        If Groq is enabled, pressing this button sends calculated figures for an
        explanation. Check the linked source values before relying on it.
      </p>
      <button
        type="button"
        className="button button--secondary"
        onClick={explain}
        disabled={busy}
      >
        {busy ? "Preparing…" : "Explain"}
      </button>
      {message && <p role="alert">{message}</p>}
      {result && (
        <div aria-live="polite">
          <p>
            {result.provider === "groq"
              ? "Groq explanation, with calculated facts below."
              : "Python-generated summary from calculated facts."}
          </p>
          <p>{result.text}</p>
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
