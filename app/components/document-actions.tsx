"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { authenticatedRequest, apiError } from "../../lib/api-client";

type Company = { id: string; name: string };

async function callDocument(path: string, method: string, body?: object) {
  const response = await authenticatedRequest(path, method, body);
  if (response.ok) return;
  const result = await response.json().catch(() => ({}));
  throw new Error(apiError(result));
}

export function DocumentActions({
  id,
  status,
  companies,
}: {
  id: string;
  status: string;
  companies: Company[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [companyId, setCompanyId] = useState(companies[0]?.id || "");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [unitScale, setUnitScale] = useState("ones");
  const [valueColumn, setValueColumn] = useState("B");

  async function process(event: React.FormEvent) {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    setBusy(true);
    setMessage("Reading your document and checking the numbers…");
    try {
      await callDocument(`/api/documents/${id}/process`, "POST", {
        company_id: String(form.get("company_id") || ""),
        period_start: String(form.get("period_start") || "") || null,
        period_end: String(form.get("period_end") || ""),
        currency: String(form.get("currency") || "").toUpperCase(),
        unit_scale: String(form.get("unit_scale") || ""),
        value_column: String(form.get("value_column") || "").toUpperCase(),
      });
      setMessage("Processing complete. Review the saved results below.");
      router.refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Processing failed.");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !window.confirm(
        "Delete this document, its private file, and all related results?",
      )
    )
      return;
    setBusy(true);
    setMessage("Deleting document…");
    try {
      await callDocument(`/api/documents/${id}`, "DELETE");
      router.push("/dashboard");
      router.refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Delete failed.");
      setBusy(false);
    }
  }

  return (
    <section className="workspace-card document-actions">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Next step</p>
          <h2>Process this document</h2>
        </div>
      </div>
      {(status === "uploaded" || status === "failed") &&
        (companies.length ? (
          <form className="metadata-form" onSubmit={process}>
            <p>
              Confirm the column and reporting details before processing. The
              app will flag uncertain figures for review.
            </p>
            <label>
              Company
              <select
                name="company_id"
                required
                value={companyId}
                onChange={(event) => setCompanyId(event.target.value)}
              >
                {companies.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Period start <span>(income and cash flow)</span>
              <input
                type="date"
                name="period_start"
                value={periodStart}
                onChange={(event) => setPeriodStart(event.target.value)}
              />
            </label>
            <label>
              Period end
              <input
                type="date"
                name="period_end"
                required
                value={periodEnd}
                onChange={(event) => setPeriodEnd(event.target.value)}
              />
            </label>
            <label>
              Currency
              <input
                name="currency"
                required
                maxLength={3}
                pattern="[A-Za-z]{3}"
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
              />
            </label>
            <label>
              Amounts shown in
              <select
                name="unit_scale"
                value={unitScale}
                onChange={(event) => setUnitScale(event.target.value)}
              >
                <option value="ones">Units</option>
                <option value="thousands">Thousands</option>
                <option value="millions">Millions</option>
                <option value="billions">Billions</option>
              </select>
            </label>
            <label>
              Amount column <span>(A, B, C…)</span>
              <input
                name="value_column"
                required
                maxLength={2}
                pattern="[A-Za-z]{1,2}"
                value={valueColumn}
                onChange={(event) => setValueColumn(event.target.value)}
              />
            </label>
            <button
              className="button button--primary"
              type="submit"
              disabled={busy}
            >
              Process document
            </button>
          </form>
        ) : (
          <p>
            Create a company record first, then return here to process this
            file.
          </p>
        ))}
      {!companies.length && (
        <Link href="/dashboard/companies">Go to companies</Link>
      )}
      {status !== "uploaded" && status !== "failed" && (
        <p>
          {status === "processing"
            ? "Processing is in progress. Refresh shortly."
            : "Processing has already run or the upload is not complete."}
        </p>
      )}
      <button
        className="button button--danger"
        type="button"
        onClick={remove}
        disabled={busy || status === "processing"}
      >
        Delete document and results
      </button>
      {message && (
        <p role="status" className="form-message">
          {message}
        </p>
      )}
    </section>
  );
}
