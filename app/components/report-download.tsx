"use client";

import { useState } from "react";
import { createClient } from "../../lib/supabase/client";

export function ReportDownload({
  companies,
}: {
  companies: { id: string; name: string }[];
}) {
  const [companyId, setCompanyId] = useState(companies[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function download() {
    if (!companyId || busy) return;
    setBusy(true);
    setMessage("Preparing workbook…");
    try {
      const { data, error } = await createClient().auth.getSession();
      if (error || !data.session)
        throw new Error("Your session expired. Sign in again.");
      const response = await fetch(
        `/api/reports/excel?company_id=${encodeURIComponent(companyId)}`,
        {
          headers: { Authorization: `Bearer ${data.session.access_token}` },
          cache: "no-store",
        },
      );
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(
          typeof result?.detail === "string"
            ? result.detail
            : "The report could not be prepared.",
        );
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const filename =
        disposition.match(/filename="([A-Za-z0-9_.-]+)"/)?.[1] ||
        "Financial_Analysis.xlsx";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("Workbook downloaded.");
    } catch (cause) {
      setMessage(
        cause instanceof Error
          ? cause.message
          : "The report could not be prepared.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="report-download">
      <label htmlFor="report-company">Company</label>
      <select
        id="report-company"
        value={companyId}
        onChange={(event) => setCompanyId(event.target.value)}
        disabled={busy}
      >
        {companies.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="button button--primary"
        onClick={download}
        disabled={!companyId || busy}
      >
        {busy ? "Preparing…" : "Download latest Excel analysis"}
      </button>
      <p role="status">{message}</p>
    </div>
  );
}
