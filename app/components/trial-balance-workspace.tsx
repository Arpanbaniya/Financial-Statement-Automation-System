"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiError, authenticatedRequest } from "../../lib/api-client";

type Row = {
  id: string;
  account: string;
  code: string;
  debit: string;
  credit: string;
  opening_debit: string;
  opening_credit: string;
  category: string | null;
  subtotal: boolean;
  errors: string[];
  excluded?: boolean;
};
type Parsed = {
  rows: Row[];
  sheets: string[];
  sheet?: string;
  issues: string[];
  has_opening: boolean;
};
type Settings = {
  company_id: string;
  period_start: string;
  period_end: string;
  currency: string;
  unit_scale: string;
  basis: string;
  sheet: string | null;
  mappings: Record<string, string>;
  exclusions: string[];
  complete: boolean;
  opening_complete: boolean;
  cash: Record<string, string | boolean> | null;
};
type Result = {
  ready: boolean;
  saved?: boolean;
  issues: string[];
  warnings: string[];
  debit: string;
  credit: string;
  difference: string;
  statements: Record<string, Record<string, string>>;
  retained_earnings: Record<string, string>;
  cash_flow_issues: string[];
  cash_bridge?: Record<string, string>;
  metrics?: {
    metric_name: string;
    value: string | null;
    unit: string;
    warnings: { message: string }[];
  }[];
  explanation?: { provider: string; fallback_used: boolean; text: string };
};
const human = (name: string) =>
  name.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
const number = (value: string | number) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const CASH_FIELDS: [string, string][] = [
  ["capex", "Cash paid for long-lived assets"],
  ["asset_sale_proceeds", "Cash received from asset sales"],
  ["other_investing", "Other investing cash flow (signed)"],
  ["borrowing", "Borrowing proceeds"],
  ["debt_repaid", "Debt principal repaid"],
  ["equity_issued", "Cash received from share / capital issues"],
  ["dividends_paid", "Dividends / drawings paid in cash"],
  ["shares_repurchased", "Cash paid to repurchase shares"],
  ["other_financing", "Other financing cash flow (signed)"],
  ["operating_adjustments", "Other operating adjustments (signed)"],
  ["fx_effect", "Exchange-rate effect on cash (signed)"],
];

export function TrialBalanceWorkspace({
  companies,
  documents,
  selected,
}: {
  companies: { id: string; name: string }[];
  documents: { id: string; original_filename: string; status: string }[];
  selected: string;
}) {
  const [documentId, setDocumentId] = useState(
    documents.some((item) => item.id === selected)
      ? selected
      : documents[0]?.id || "",
  );
  const [sheet, setSheet] = useState("");
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [categories, setCategories] = useState<{ id: string; label: string }[]>(
    [],
  );
  const [settings, setSettings] = useState<Settings>({
    company_id: companies[0]?.id || "",
    period_start: "",
    period_end: "",
    currency: "USD",
    unit_scale: "ones",
    basis: "pre_closing",
    sheet: null,
    mappings: {},
    exclusions: [],
    complete: false,
    opening_complete: false,
    cash: null,
  });
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [cashEnabled, setCashEnabled] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    async function load() {
      setBusy(true);
      setMessage("Reading your trial balance…");
      setResult(null);
      setParsed(null);
      setPage(0);
      try {
        const response = await authenticatedRequest(
          `/api/trial-balance/${documentId}${sheet ? `?sheet=${encodeURIComponent(sheet)}` : ""}`,
        );
        const data = await response.json();
        if (!response.ok) throw new Error(apiError(data));
        if (cancelled) return;
        setParsed(data.parsed);
        setCategories(data.categories);
        if (data.settings && (!sheet || data.settings.sheet === sheet)) {
          setSettings(data.settings);
          setCashEnabled(Boolean(data.settings.cash));
        } else {
          setSettings((previous) => ({
            ...previous,
            sheet: data.parsed.sheet || null,
            mappings: {},
            exclusions: [],
            complete: false,
            opening_complete: false,
            cash: null,
          }));
          setCashEnabled(false);
        }
        setMessage(
          data.settings
            ? "Saved mappings loaded. Check or regenerate to view the current results."
            : "Review the reporting details and account mappings below.",
        );
      } catch (cause) {
        if (!cancelled)
          setMessage(
            cause instanceof Error
              ? cause.message
              : "Could not read trial balance.",
          );
      } finally {
        if (!cancelled) setBusy(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [documentId, sheet]);

  function change(patch: Partial<Settings>) {
    setSettings((previous) => ({ ...previous, ...patch }));
    setResult(null);
  }
  async function run(action: string) {
    if (!formRef.current?.reportValidity()) return;
    const form = new FormData(formRef.current);
    const payload: Settings = {
      ...settings,
      period_start: String(form.get("period_start")),
      period_end: String(form.get("period_end")),
      sheet: parsed?.sheet || null,
      cash: cashEnabled
        ? {
            ...Object.fromEntries(
              CASH_FIELDS.map(([name]) => [name, String(form.get(name) ?? "")]),
            ),
            notes: String(form.get("cash_notes") || ""),
            confirmed: form.get("cash_confirmed") === "on",
          }
        : null,
    };
    setSettings(payload);
    setBusy(true);
    setMessage(
      action === "generate"
        ? "Generating and saving your statements…"
        : "Checking your figures…",
    );
    try {
      const response = await authenticatedRequest(
        `/api/trial-balance/${documentId}/${action}`,
        "POST",
        payload,
      );
      if (action === "excel" && response.ok) {
        const url = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `Trial_Balance_${payload.period_end}.xlsx`;
        anchor.click();
        URL.revokeObjectURL(url);
        setMessage("Workbook downloaded.");
        return;
      }
      const data = await response.json();
      if (data.issues) setResult(data);
      if (!response.ok) throw new Error(apiError(data));
      setMessage(
        data.saved
          ? "Statements saved. Analysis and reports now use these results."
          : data.ready
            ? "Checks complete. Your statements are ready to review."
            : "Resolve the issues shown below before generating.",
      );
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }
  const visible = (parsed?.rows || []).filter((row) =>
    `${row.account} ${row.code}`.toLowerCase().includes(search.toLowerCase()),
  );
  const income = result?.statements?.income_statement;
  const balance = result?.statements?.balance_sheet;
  if (!companies.length)
    return (
      <section className="workspace-card">
        <h2>Add your company first</h2>
        <p>Your statements need a company and reporting period.</p>
        <Link href="/dashboard/companies">Create a company</Link>
      </section>
    );
  if (!documents.length)
    return (
      <section className="workspace-card">
        <h2>Your books start here</h2>
        <p>
          Upload a CSV or XLSX with Account Name, Debit and Credit columns. An
          optional Account Code keeps account identities clear.
        </p>
        <p>
          For cash flow, also include Opening Debit and Opening Credit with the
          balances at the day before your reporting period.
        </p>
        <Link href="/dashboard#upload">Upload your first trial balance</Link> ·{" "}
        <a href="/trial-balance-template.csv" download>
          Download blank CSV template
        </a>
      </section>
    );
  return (
    <>
      <section className="workspace-card">
        <div className="section-heading">
          <h2>1. Choose your source</h2>
          <a href="/trial-balance-template.csv" download>
            CSV template
          </a>
        </div>
        <label className="tb-field">
          Uploaded trial balance
          <select
            disabled={busy}
            value={documentId}
            onChange={(event) => {
              setDocumentId(event.target.value);
              setSheet("");
            }}
          >
            <option value="" disabled>
              Select a document
            </option>
            {documents.map((item) => (
              <option key={item.id} value={item.id}>
                {item.original_filename}
              </option>
            ))}
          </select>
        </label>
        {parsed && parsed.sheets.length > 1 && (
          <label className="tb-field">
            Worksheet
            <select
              value={sheet || parsed.sheet || ""}
              onChange={(event) => setSheet(event.target.value)}
              disabled={busy}
            >
              <option value="" disabled>
                Choose a worksheet
              </option>
              {parsed.sheets.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
        )}
        <p>
          Use values exported from your accounting system. Formula cells must be
          converted to values first. Up to 1,000 account rows; one reporting
          currency.
        </p>
      </section>
      <p role="status" aria-live="polite" className="form-message">
        {message}
      </p>
      {parsed && (
        <form
          ref={formRef}
          onSubmit={(event) => {
            event.preventDefault();
            void run("generate");
          }}
          onChange={() => setResult(null)}
        >
          <fieldset disabled={busy} className="tb-fieldset">
            <section className="workspace-card">
              <h2>2. Reporting details</h2>
              <div className="tb-form-grid">
                <label>
                  Company
                  <select
                    value={settings.company_id}
                    onChange={(event) =>
                      change({ company_id: event.target.value })
                    }
                  >
                    {companies.map((company) => (
                      <option key={company.id} value={company.id}>
                        {company.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Period start
                  <input
                    name="period_start"
                    type="date"
                    required
                    value={settings.period_start}
                    onChange={(event) =>
                      change({ period_start: event.target.value })
                    }
                  />
                </label>
                <label>
                  Period end
                  <input
                    name="period_end"
                    type="date"
                    required
                    value={settings.period_end}
                    onChange={(event) =>
                      change({ period_end: event.target.value })
                    }
                  />
                </label>
                <label>
                  Currency
                  <input
                    value={settings.currency}
                    required
                    pattern="[A-Z]{3}"
                    maxLength={3}
                    onChange={(event) =>
                      change({ currency: event.target.value.toUpperCase() })
                    }
                  />
                </label>
                <label>
                  Source units
                  <select
                    value={settings.unit_scale}
                    onChange={(event) =>
                      change({ unit_scale: event.target.value })
                    }
                  >
                    {["ones", "thousands", "millions", "billions"].map(
                      (unit) => (
                        <option key={unit}>{unit}</option>
                      ),
                    )}
                  </select>
                </label>
                <label>
                  Trial-balance basis
                  <select
                    value={settings.basis}
                    onChange={(event) => change({ basis: event.target.value })}
                  >
                    <option value="pre_closing">
                      Pre-closing: income & expenses still present
                    </option>
                    <option value="post_closing">
                      Post-closing: balance sheet only
                    </option>
                  </select>
                </label>
              </div>
              <p>
                For pre-closing books, retained earnings excludes this period’s
                profit. Dividends and drawings belong in equity. Include
                adjustment entries in the uploaded balances.
              </p>
            </section>
            <section className="workspace-card">
              <div className="section-heading">
                <div>
                  <h2>3. Review account categories</h2>
                  <p>
                    Exact name matches are suggestions. Review every mapping,
                    including debit balances in normally credit accounts.
                  </p>
                </div>
                <label>
                  Find an account
                  <input
                    type="search"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(0);
                    }}
                  />
                </label>
              </div>
              <div className="table-scroll">
                <table className="data-table tb-mapping">
                  <thead>
                    <tr>
                      <th>Include</th>
                      <th>Account / source</th>
                      <th>Debit</th>
                      <th>Credit</th>
                      <th>Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.slice(page * 50, (page + 1) * 50).map((row) => (
                      <tr
                        key={row.id}
                        className={
                          row.subtotal || settings.exclusions.includes(row.id)
                            ? "tb-excluded"
                            : ""
                        }
                      >
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Include ${row.account}`}
                            disabled={row.subtotal}
                            checked={
                              !row.subtotal &&
                              !settings.exclusions.includes(row.id)
                            }
                            onChange={(event) =>
                              change({
                                exclusions: event.target.checked
                                  ? settings.exclusions.filter(
                                      (id) => id !== row.id,
                                    )
                                  : [...settings.exclusions, row.id],
                              })
                            }
                          />
                        </td>
                        <th scope="row">
                          {row.code && <small>{row.code} · </small>}
                          {row.account || "Missing account name"}
                          <small className="tb-source">
                            {row.id}
                            {row.subtotal ? " · subtotal excluded" : ""}
                            {row.errors.length > 0
                              ? ` · ${row.errors.join("; ")}`
                              : ""}
                          </small>
                        </th>
                        <td>{number(row.debit)}</td>
                        <td>{number(row.credit)}</td>
                        <td>
                          <select
                            aria-label={`Category for ${row.account}`}
                            disabled={
                              row.subtotal ||
                              settings.exclusions.includes(row.id)
                            }
                            value={
                              settings.mappings[row.id] || row.category || ""
                            }
                            onChange={(event) =>
                              change({
                                mappings: {
                                  ...settings.mappings,
                                  [row.id]: event.target.value,
                                },
                              })
                            }
                          >
                            <option value="" disabled>
                              Choose category
                            </option>
                            {categories.map((category) => (
                              <option value={category.id} key={category.id}>
                                {category.label}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {visible.length > 50 && (
                <div className="tb-actions">
                  <button
                    type="button"
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page + 1} of {Math.ceil(visible.length / 50)}
                  </span>
                  <button
                    type="button"
                    disabled={(page + 1) * 50 >= visible.length}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </button>
                </div>
              )}
              <label className="tb-check">
                <input
                  type="checkbox"
                  checked={settings.complete}
                  onChange={(event) =>
                    change({ complete: event.target.checked })
                  }
                />
                I reviewed the mappings and exclusions. This is the complete
                adjusted trial balance; omitted categories have zero balances.
              </label>
              {parsed.has_opening && (
                <label className="tb-check">
                  <input
                    type="checkbox"
                    checked={settings.opening_complete}
                    onChange={(event) =>
                      change({ opening_complete: event.target.checked })
                    }
                  />
                  Opening columns contain complete post-closing balances at the
                  day before the period starts.
                </label>
              )}
            </section>
            <section className="workspace-card">
              <h2>
                4. Cash flow details{" "}
                <span className="tb-optional">Optional</span>
              </h2>
              <p>
                Cash flow needs opening balances and cash movement details.
                Balance-sheet changes alone cannot distinguish cash payments
                from noncash entries.
              </p>
              <label className="tb-check">
                <input
                  type="checkbox"
                  checked={cashEnabled}
                  onChange={(event) => {
                    setCashEnabled(event.target.checked);
                    setResult(null);
                  }}
                />
                Add a cash movement schedule
              </label>
              {cashEnabled && (
                <>
                  <p>
                    Enter amounts in the same units as the trial balance,
                    including explicit zeros. Positive amounts for
                    receipts/payments; signed fields use positive for cash
                    sources and negative for uses. Interest and income taxes are
                    treated as operating cash flows.
                  </p>
                  <div className="tb-form-grid">
                    {CASH_FIELDS.map(([name, caption]) => (
                      <label key={name}>
                        {caption}
                        <input
                          name={name}
                          type="number"
                          step="0.0001"
                          required
                          defaultValue={String(settings.cash?.[name] ?? "")}
                          min={caption.includes("signed") ? undefined : "0"}
                        />
                      </label>
                    ))}
                  </div>
                  <label className="tb-field">
                    Basis and adjustment details
                    <textarea
                      name="cash_notes"
                      required
                      maxLength={2000}
                      defaultValue={String(settings.cash?.notes || "")}
                      placeholder="Explain noncash adjustments, asset disposals, FX and any other movements. Write ‘None’ only if reviewed and not applicable."
                    />
                  </label>
                  <label className="tb-check">
                    <input
                      type="checkbox"
                      name="cash_confirmed"
                      defaultChecked={settings.cash?.confirmed === true}
                      required
                    />
                    I included all investing and financing cash movements and
                    adjusted operating movements for acquisitions, FX,
                    reclassifications and other noncash changes. Depreciation is
                    already added back automatically.
                  </label>
                </>
              )}
            </section>
            <div className="tb-actions tb-actions--sticky">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void run("check")}
              >
                Check & preview
              </button>
              <button type="submit" className="button">
                Generate & save statements
              </button>
              <span>
                Changes replace this document’s previous generated results.
              </span>
            </div>
          </fieldset>
        </form>
      )}
      {result && (
        <section className="tb-results" aria-label="Generation results">
          <div className="stat-grid">
            <div className="stat-card">
              <span>Total debit</span>
              <strong>{number(result.debit)}</strong>
            </div>
            <div className="stat-card">
              <span>Total credit</span>
              <strong>{number(result.credit)}</strong>
            </div>
            <div className="stat-card">
              <span>Difference · {settings.currency}</span>
              <strong>{number(result.difference)}</strong>
            </div>
            <div className="stat-card">
              <span>Statements available</span>
              <strong>{Object.keys(result.statements).length} / 3</strong>
            </div>
          </div>
          {result.issues.length > 0 && (
            <section className="workspace-card" role="alert">
              <h2>Resolve these items</h2>
              <ul>
                {result.issues.map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </section>
          )}
          {result.ready && (
            <>
              <div className="tb-actions">
                <button
                  disabled={busy}
                  className="button button--secondary"
                  onClick={() => void run("excel")}
                >
                  Download Excel
                </button>
                <button
                  disabled={busy}
                  className="button button--secondary"
                  onClick={() => void run("explain")}
                >
                  Explain the results
                </button>
                <Link href={`/dashboard/documents/${documentId}`}>
                  Source document & saved results
                </Link>
              </div>
              <div className="tb-chart-grid">
                {[
                  [
                    "Profitability",
                    income,
                    [
                      "revenue",
                      "gross_profit",
                      "operating_income",
                      "net_income",
                    ],
                  ],
                  [
                    "Financial position",
                    balance,
                    [
                      "total_assets",
                      "total_liabilities",
                      "shareholders_equity",
                    ],
                  ],
                ].map(
                  ([title, values, fields]) =>
                    values && (
                      <section className="workspace-card" key={String(title)}>
                        <h2>{String(title)}</h2>
                        <p>{settings.currency} · normalized ones</p>
                        <div className="tb-chart">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                              accessibilityLayer
                              data={(fields as string[]).map((field) => ({
                                name: human(field),
                                value: Number(
                                  (values as Record<string, string>)[field],
                                ),
                              }))}
                              layout="vertical"
                              margin={{ left: 0, right: 20 }}
                            >
                              <CartesianGrid
                                strokeDasharray="3 3"
                                horizontal={false}
                              />
                              <XAxis
                                type="number"
                                tickFormatter={(value) =>
                                  Intl.NumberFormat(undefined, {
                                    notation: "compact",
                                  }).format(value)
                                }
                              />
                              <YAxis
                                dataKey="name"
                                type="category"
                                width={135}
                                tick={{ fontSize: 12 }}
                              />
                              <Tooltip
                                formatter={(value) => number(Number(value))}
                              />
                              <Bar
                                dataKey="value"
                                fill="#24644f"
                                radius={[0, 5, 5, 0]}
                              />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </section>
                    ),
                )}
              </div>
              <section className="workspace-card">
                <h2>How profit reaches equity</h2>
                <div className="tb-equity-flow">
                  {[
                    ["Brought forward", "brought_forward"],
                    ["+ Profit / loss", "profit"],
                    ["− Distributions", "distributions"],
                    ["= Closing retained earnings", "closing"],
                  ].map(([caption, field]) => (
                    <div key={field}>
                      <span>{caption}</span>
                      <strong>{number(result.retained_earnings[field])}</strong>
                    </div>
                  ))}
                </div>
              </section>
              {Object.entries(result.statements).map(([kind, values]) => (
                <section className="workspace-card" key={kind}>
                  <h2>{human(kind)}</h2>
                  <p>
                    {settings.currency} ·{" "}
                    {kind === "balance_sheet"
                      ? `As at ${settings.period_end}`
                      : `${settings.period_start} to ${settings.period_end}`}{" "}
                    · calculated from reviewed accounts
                  </p>
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Line item</th>
                          <th>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(values).map(([field, value]) => (
                          <tr
                            key={field}
                            className={
                              /^(total_|net_income|gross_profit|operating_income|shareholders_equity|.*cash_flow)/.test(
                                field,
                              )
                                ? "tb-total"
                                : ""
                            }
                          >
                            <th scope="row">{human(field)}</th>
                            <td>{number(value)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
              <section className="workspace-card">
                <h2>Cash flow reconciliation</h2>
                {result.cash_flow_issues.length ? (
                  <ul>
                    {result.cash_flow_issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                ) : (
                  <p>
                    Opening cash + operating + investing + financing +
                    exchange-rate effect = closing cash.
                  </p>
                )}
                {result.cash_bridge && (
                  <dl className="tb-equity-flow">
                    {Object.entries(result.cash_bridge).map(([name, value]) => (
                      <div key={name}>
                        <dt>{human(name)}</dt>
                        <dd>{number(value)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
              <section className="workspace-card">
                <h2>Ratios & analysis</h2>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Value</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.metrics?.map((metric) => (
                        <tr key={metric.metric_name}>
                          <th scope="row">{human(metric.metric_name)}</th>
                          <td>
                            {metric.value === null
                              ? "Unavailable"
                              : `${number(metric.value)} ${metric.unit === "percent" ? "%" : metric.unit === "currency" ? settings.currency : metric.unit}`}
                          </td>
                          <td>
                            {metric.warnings.map((w) => w.message).join(" ") ||
                              "Calculated from the generated statements."}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              {result.explanation && (
                <section className="workspace-card">
                  <p className="eyebrow">
                    {result.explanation.fallback_used
                      ? "Deterministic explanation"
                      : "Groq explanation"}
                  </p>
                  <h2>What the figures say</h2>
                  <p>{result.explanation.text}</p>
                </section>
              )}
              {result.warnings.length > 0 && (
                <section className="workspace-card">
                  <h2>Import notes</h2>
                  <ul>
                    {result.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </section>
      )}
    </>
  );
}
