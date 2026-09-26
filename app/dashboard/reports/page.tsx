import Link from "next/link";
import { ReportDownload } from "../../components/report-download";
import { requireWorkspace } from "../../../lib/require-workspace";
import { formatDate, label } from "../../../lib/workspace";

export default async function ReportsPage() {
  const { supabase, user } = await requireWorkspace();
  const [companies, reports] = await Promise.all([
    supabase
      .from("companies")
      .select("id,name")
      .eq("user_id", user.id)
      .order("name"),
    supabase
      .from("reports")
      .select("id,company_id,document_id,status,is_stale,created_at")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false })
      .limit(100),
  ]);
  const companyById = new Map(
    (companies.data || []).map((item) => [item.id, item.name]),
  );
  return (
    <main className="workspace__main">
      <p className="eyebrow">Exports</p>
      <h1>Reports</h1>
      <p className="description">
        Download an Excel workbook from the latest accepted statements for a
        company. The workbook contains source data, methods, validation checks,
        and calculated measures.
      </p>
      {(companies.error || reports.error) && (
        <p role="alert" className="form-message form-message--error">
          Report data could not be loaded.
        </p>
      )}
      <section className="workspace-card">
        <h2>New Excel analysis</h2>
        {!companies.data?.length ? (
          <p>
            No companies are available yet. A company needs accepted statements
            before it can be exported.
          </p>
        ) : (
          <ReportDownload companies={companies.data} />
        )}
        <p>
          On-demand downloads are generated privately and are not saved in
          report history.
        </p>
      </section>
      <section className="workspace-card">
        <h2>Saved report history</h2>
        {!reports.data?.length ? (
          <p>No saved reports yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Requested</th>
                  <th scope="col">Status</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {reports.data.map((item) => (
                  <tr key={item.id}>
                    <th scope="row">
                      {companyById.get(item.company_id) || "Unknown company"}
                    </th>
                    <td>{formatDate(item.created_at)}</td>
                    <td>
                      {label(item.status)}
                      {item.is_stale ? " · stale" : ""}
                    </td>
                    <td>
                      {item.document_id ? (
                        <Link href={`/dashboard/documents/${item.document_id}`}>
                          Document
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
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
