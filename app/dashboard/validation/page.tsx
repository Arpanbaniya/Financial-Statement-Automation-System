import Link from "next/link";
import { requireWorkspace } from "../../../lib/require-workspace";
import { formatDate, formatNumber, label } from "../../../lib/workspace";
import { resolveReview } from "./actions";

function percent(part: number, total: number): string {
  return total ? `${formatNumber((part / total) * 100, 1)}%` : "Unavailable";
}

export default async function ValidationPage({
  searchParams,
}: {
  searchParams: Promise<{ result?: string }>;
}) {
  const { supabase, user } = await requireWorkspace();
  const [checks, reviews, lines, statements, fields, events] =
    await Promise.all([
      supabase
        .from("validation_results")
        .select(
          "id,document_id,statement_id,check_name,status,severity,message,expected_value,actual_value",
        )
        .eq("user_id", user.id)
        .eq("is_stale", false)
        .order("created_at", { ascending: false })
        .limit(1000),
      supabase
        .from("manual_reviews")
        .select(
          "id,line_item_id,status,suggested_mapping,review_note,created_at",
        )
        .eq("user_id", user.id)
        .eq("status", "open")
        .order("created_at")
        .limit(1000),
      supabase
        .from("financial_line_items")
        .select(
          "id,statement_id,canonical_name,original_label,original_value,review_status,source_page,source_sheet,source_cell",
        )
        .eq("user_id", user.id)
        .limit(1000),
      supabase
        .from("financial_statements")
        .select(
          "id,document_id,statement_type,period_end,currency,unit_scale,detection_confidence",
        )
        .eq("user_id", user.id)
        .limit(1000),
      supabase
        .from("canonical_fields")
        .select("statement_type,machine_name,is_core_field"),
      supabase
        .from("audit_events")
        .select("id,document_id,entity_type,action,metadata,created_at")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(20),
    ]);
  const { result } = await searchParams;
  const loadError = [checks, reviews, lines, statements, fields, events].some(
    (item) => item.error,
  );
  const statementById = new Map(
    (statements.data || []).map((item) => [item.id, item]),
  );
  const lineById = new Map((lines.data || []).map((item) => [item.id, item]));
  const recognized = (statements.data || []).filter(
    (item) => item.detection_confidence !== null,
  );
  const meanConfidence = recognized.length
    ? percent(
        recognized.reduce(
          (sum, item) => sum + (item.detection_confidence || 0),
          0,
        ),
        recognized.length,
      )
    : "Unavailable";
  const acceptedLines = (lines.data || []).filter(
    (item) => item.review_status === "accepted",
  );
  const sourceLines = acceptedLines.filter(
    (item) =>
      item.original_value !== null &&
      (item.source_page !== null || item.source_cell !== null),
  );
  const coreTargets = (statements.data || []).flatMap((statement) =>
    (fields.data || [])
      .filter(
        (field) =>
          field.statement_type === statement.statement_type &&
          field.is_core_field,
      )
      .map((field) => ({
        statementId: statement.id,
        field: field.machine_name,
      })),
  );
  const corePresent = coreTargets.filter((target) =>
    acceptedLines.some(
      (item) =>
        item.statement_id === target.statementId &&
        item.canonical_name === target.field,
    ),
  ).length;
  const applicable = (checks.data || []).filter(
    (item) => item.status !== "not_applicable",
  );
  const passed = applicable.filter((item) => item.status === "passed").length;
  const limited = [checks.data, reviews.data, lines.data, statements.data].some(
    (data) => data?.length === 1000,
  );
  const quality = [
    ["Statement detection confidence", meanConfidence],
    [
      "Mapping completeness",
      percent(acceptedLines.length, lines.data?.length || 0),
    ],
    ["Core field completeness", percent(corePresent, coreTargets.length)],
    ["Validation checks passed", percent(passed, applicable.length)],
    ["Unresolved review items", String(reviews.data?.length ?? "Unavailable")],
    ["Source coverage", percent(sourceLines.length, acceptedLines.length)],
  ];
  return (
    <main className="workspace__main">
      <p className="eyebrow">Checks and traceability</p>
      <h1>Validation</h1>
      <p className="description">
        Each indicator stands on its own. There is no combined quality score.
      </p>
      {result === "saved" && (
        <p role="status" className="form-message form-message--success">
          Review saved and audit history updated.
        </p>
      )}
      {result === "invalid" && (
        <p role="alert" className="form-message form-message--error">
          Choose a valid action and provide a reason.
        </p>
      )}
      {result === "failed" && (
        <p role="alert" className="form-message form-message--error">
          The review could not be saved. Check the selected field and try again.
        </p>
      )}
      {loadError && (
        <p role="alert" className="form-message form-message--error">
          Some validation data could not be loaded.
        </p>
      )}
      {limited && (
        <p role="status">
          Indicators cover the first 1,000 rows per category. Narrow the data
          before interpreting them as totals.
        </p>
      )}
      <section className="workspace-card">
        <h2>Data quality indicators</h2>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Indicator</th>
                <th scope="col">Observed value</th>
              </tr>
            </thead>
            <tbody>
              {quality.map(([name, value]) => (
                <tr key={name}>
                  <th scope="row">{name}</th>
                  <td>{loadError ? "Unavailable" : value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Detection confidence is rule strength, not a statistical probability.
          Core fields are project completeness targets, not universal filing
          requirements.
        </p>
      </section>
      <div className="stat-grid">
        {(["passed", "warning", "failed", "not_applicable"] as const).map(
          (status) => (
            <div className="stat-card" key={status}>
              <strong>
                {checks.data?.filter((item) => item.status === status).length ??
                  "—"}
              </strong>
              <span>{label(status)} checks</span>
            </div>
          ),
        )}
      </div>
      <section className="workspace-card">
        <h2>Current checks</h2>
        {!checks.data?.length ? (
          <p>No validation results have been stored yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Result</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Actual</th>
                  <th scope="col">Explanation</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {checks.data.map((item) => (
                  <tr key={item.id}>
                    <th scope="row">{label(item.check_name)}</th>
                    <td>{label(item.status)}</td>
                    <td>
                      {item.expected_value === null
                        ? "—"
                        : formatNumber(item.expected_value, 2)}
                    </td>
                    <td>
                      {item.actual_value === null
                        ? "—"
                        : formatNumber(item.actual_value, 2)}
                    </td>
                    <td>{item.message || "—"}</td>
                    <td>
                      <Link
                        href={`/dashboard/documents/${item.document_id}${item.statement_id ? `#statement-${item.statement_id}` : ""}`}
                      >
                        Document
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="workspace-card">
        <h2>Manual review queue</h2>
        {!reviews.data?.length ? (
          <p>No open mapping reviews.</p>
        ) : (
          reviews.data.map((review) => {
            const line = lineById.get(review.line_item_id);
            const statement = line
              ? statementById.get(line.statement_id)
              : undefined;
            const choices = (fields.data || []).filter(
              (field) => field.statement_type === statement?.statement_type,
            );
            return (
              <div className="review-card" key={review.id}>
                <h3>{line?.original_label || "Source line unavailable"}</h3>
                <p>
                  Suggested:{" "}
                  {review.suggested_mapping
                    ? label(review.suggested_mapping)
                    : "No suggestion"}
                  . Original value: {line?.original_value ?? "Unavailable"}.
                </p>
                {statement && line && (
                  <p>
                    <Link
                      href={`/dashboard/documents/${statement.document_id}#line-${line.id}`}
                    >
                      Inspect the source line
                    </Link>
                  </p>
                )}
                {choices.length ? (
                  <form action={resolveReview} className="review-form">
                    <input type="hidden" name="review_id" value={review.id} />
                    <label htmlFor={`mapping-${review.id}`}>
                      Canonical field
                    </label>
                    <select
                      id={`mapping-${review.id}`}
                      name="selected_mapping"
                      defaultValue={review.suggested_mapping || ""}
                    >
                      <option value="">Choose a field</option>
                      {choices.map((field) => (
                        <option
                          key={field.machine_name}
                          value={field.machine_name}
                        >
                          {label(field.machine_name)}
                        </option>
                      ))}
                    </select>
                    <label htmlFor={`reason-${review.id}`}>
                      Reason for decision
                    </label>
                    <input
                      id={`reason-${review.id}`}
                      name="reason"
                      maxLength={1000}
                      required
                    />
                    <div className="actions">
                      <button
                        className="button button--primary"
                        type="submit"
                        name="action"
                        value="accept"
                      >
                        Accept mapping
                      </button>
                      <button
                        className="button button--secondary"
                        type="submit"
                        name="action"
                        value="dismiss"
                      >
                        Dismiss review
                      </button>
                    </div>
                  </form>
                ) : (
                  <p>
                    Field choices are unavailable; review actions will work
                    after the audit migration is applied.
                  </p>
                )}
              </div>
            );
          })
        )}
      </section>
      <section className="workspace-card">
        <h2>Recent audit events</h2>
        {!events.data?.length ? (
          <p>No audit events have been recorded yet.</p>
        ) : (
          <ul className="plain-list">
            {events.data.map((event) => {
              const metadata =
                event.metadata && typeof event.metadata === "object"
                  ? (event.metadata as { reason?: string })
                  : {};
              return (
                <li key={event.id}>
                  <span>
                    {formatDate(event.created_at)} · {label(event.action)} ·{" "}
                    {label(event.entity_type)}
                    {metadata.reason ? ` · ${metadata.reason}` : ""}
                  </span>
                  {event.document_id && (
                    <Link href={`/dashboard/documents/${event.document_id}`}>
                      Source
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </main>
  );
}
