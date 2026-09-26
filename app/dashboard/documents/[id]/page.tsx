import Link from "next/link";
import { notFound } from "next/navigation";
import { requireWorkspace } from "../../../../lib/require-workspace";
import { formatDate, formatNumber, label } from "../../../../lib/workspace";

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { supabase, user } = await requireWorkspace();
  const { data: document, error: documentError } = await supabase
    .from("documents")
    .select(
      "id,company_id,original_filename,file_size,mime_type,status,storage_path,created_at,updated_at",
    )
    .eq("id", id)
    .eq("user_id", user.id)
    .maybeSingle();
  if (!document && !documentError) notFound();
  if (!document)
    return (
      <main className="workspace__main">
        <p role="alert">Document could not be loaded.</p>
      </main>
    );
  const [statements, jobs, checks, signed] = await Promise.all([
    supabase
      .from("financial_statements")
      .select(
        "id,statement_type,period_start,period_end,currency,unit_scale,status",
      )
      .eq("user_id", user.id)
      .eq("document_id", id)
      .order("period_end", { ascending: false }),
    supabase
      .from("processing_jobs")
      .select("id,status,stage,progress,error_message,created_at")
      .eq("user_id", user.id)
      .eq("document_id", id)
      .order("created_at", { ascending: false }),
    supabase
      .from("validation_results")
      .select(
        "id,check_name,status,severity,message,statement_id,expected_value,actual_value",
      )
      .eq("user_id", user.id)
      .eq("document_id", id)
      .eq("is_stale", false),
    supabase.storage
      .from("financial-documents")
      .createSignedUrl(document.storage_path, 60),
  ]);
  const statementIds = (statements.data || []).map((item) => item.id);
  const items = statementIds.length
    ? await supabase
        .from("financial_line_items")
        .select(
          "id,statement_id,canonical_name,original_label,original_value,normalized_value,source_page,source_sheet,source_cell,review_status",
        )
        .eq("user_id", user.id)
        .in("statement_id", statementIds)
        .limit(1000)
    : null;
  const error = statements.error || jobs.error || checks.error || items?.error;
  return (
    <main className="workspace__main">
      <p className="eyebrow">Document detail</p>
      <h1>{document.original_filename}</h1>
      {error && (
        <p role="alert" className="form-message form-message--error">
          Some document details could not be loaded.
        </p>
      )}
      <div className="stat-grid">
        <div className="stat-card">
          <strong>{label(document.status)}</strong>
          <span>Upload status</span>
        </div>
        <div className="stat-card">
          <strong>{formatNumber(document.file_size / 1024, 0)} KB</strong>
          <span>File size</span>
        </div>
        <div className="stat-card">
          <strong>{statements.data?.length ?? "—"}</strong>
          <span>Detected statements</span>
        </div>
        <div className="stat-card">
          <strong>
            {checks.data?.filter(
              (item) => item.status === "warning" || item.status === "failed",
            ).length ?? "—"}
          </strong>
          <span>Warnings or failures</span>
        </div>
      </div>
      <section className="workspace-card">
        <h2>Source file</h2>
        <p>
          Uploaded {formatDate(document.created_at)} · {document.mime_type}.
        </p>
        {signed.data?.signedUrl ? (
          <a
            href={signed.data.signedUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open original file (link expires in one minute)
          </a>
        ) : (
          <p>Source preview is unavailable right now.</p>
        )}
        {document.company_id && (
          <p>
            <Link href={`/dashboard/companies/${document.company_id}`}>
              View company overview
            </Link>
          </p>
        )}
      </section>
      <section className="workspace-card">
        <h2>Extraction and processing</h2>
        {!jobs.data?.length ? (
          <p>
            No processing job has run yet. The uploaded file has not been
            extracted or analyzed.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Stage</th>
                  <th scope="col">Progress</th>
                  <th scope="col">Status</th>
                  <th scope="col">Issue</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.map((job) => (
                  <tr key={job.id}>
                    <th scope="row">{formatDate(job.created_at)}</th>
                    <td>{label(job.stage)}</td>
                    <td>{job.progress}%</td>
                    <td>{label(job.status)}</td>
                    <td>{job.error_message || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="workspace-card">
        <h2>Statements and source lines</h2>
        {!statements.data?.length ? (
          <p>
            No statement detection results have been stored for this document.
          </p>
        ) : (
          statements.data.map((statement) => (
            <div
              id={`statement-${statement.id}`}
              className="statement-block"
              key={statement.id}
            >
              <h3>
                {label(statement.statement_type)} ·{" "}
                {formatDate(statement.period_end)}
              </h3>
              <p>
                {statement.currency || "Currency unresolved"} ·{" "}
                {statement.unit_scale || "Unit unresolved"} ·{" "}
                {label(statement.status)}
              </p>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Original label</th>
                      <th scope="col">Mapped field</th>
                      <th scope="col">Original value</th>
                      <th scope="col">Normalized value</th>
                      <th scope="col">Source location</th>
                      <th scope="col">Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(items?.data || [])
                      .filter((item) => item.statement_id === statement.id)
                      .map((item) => (
                        <tr id={`line-${item.id}`} key={item.id}>
                          <th scope="row">{item.original_label}</th>
                          <td>
                            {item.canonical_name
                              ? label(item.canonical_name)
                              : "Unmapped"}
                          </td>
                          <td>{item.original_value ?? "—"}</td>
                          <td>
                            {item.normalized_value === null
                              ? "Unavailable"
                              : formatNumber(item.normalized_value, 2)}
                          </td>
                          <td>
                            {item.source_page
                              ? `Page ${item.source_page}`
                              : item.source_sheet
                                ? `${item.source_sheet}${item.source_cell ? `!${item.source_cell}` : ""}`
                                : "Location unavailable"}
                          </td>
                          <td>{label(item.review_status)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </section>
      <section className="workspace-card">
        <h2>Validation</h2>
        {!checks.data?.length ? (
          <p>No validation checks are stored yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Status</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Actual</th>
                  <th scope="col">Explanation</th>
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
