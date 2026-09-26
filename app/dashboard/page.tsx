import Link from "next/link";
import { signOut } from "../auth/actions";
import { ApiHealth } from "../components/api-health";
import { DocumentUpload } from "../components/document-upload";
import { createClient } from "../../lib/supabase/server";
import { formatDate, label } from "../../lib/workspace";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  const [{ data: profile }, documents, jobs, companies, checks, reviews] =
    await Promise.all([
      supabase
        .from("profiles")
        .select("display_name")
        .eq("id", user!.id)
        .maybeSingle(),
      supabase
        .from("documents")
        .select("id,original_filename,status,created_at")
        .eq("user_id", user!.id)
        .order("created_at", { ascending: false })
        .limit(8),
      supabase
        .from("processing_jobs")
        .select("id,document_id,status,stage,progress,created_at")
        .eq("user_id", user!.id)
        .order("created_at", { ascending: false })
        .limit(6),
      supabase
        .from("companies")
        .select("id,name,ticker")
        .eq("user_id", user!.id)
        .order("name")
        .limit(8),
      supabase
        .from("validation_results")
        .select("id,document_id,check_name,status")
        .eq("user_id", user!.id)
        .eq("is_stale", false)
        .in("status", ["warning", "failed"])
        .limit(8),
      supabase
        .from("manual_reviews")
        .select("id,status")
        .eq("user_id", user!.id)
        .eq("status", "open")
        .limit(1000),
    ]);
  const { error } = await searchParams;
  const loadError = [documents, jobs, companies, checks, reviews].some(
    (item) => item.error,
  );
  return (
    <main className="workspace__main">
      <div className="workspace__heading">
        <div>
          <p className="eyebrow">Private workspace</p>
          <h1>Overview</h1>
          <p className="description">
            Signed in as {profile?.display_name || user?.email}. Your documents
            and analysis are private to this account.
          </p>
        </div>
        <form action={signOut}>
          <button className="button button--secondary" type="submit">
            Sign out
          </button>
        </form>
      </div>
      {error === "signout" && (
        <p role="alert" className="form-message form-message--error">
          Sign out failed. Please try again.
        </p>
      )}
      {loadError && (
        <p role="alert" className="form-message form-message--error">
          Some workspace data could not be loaded. Refresh the page to try
          again.
        </p>
      )}
      <div className="stat-grid">
        <div className="stat-card">
          <strong>{documents.data?.length ?? "—"}</strong>
          <span>Recent documents</span>
        </div>
        <div className="stat-card">
          <strong>{companies.data?.length ?? "—"}</strong>
          <span>Companies shown</span>
        </div>
        <div className="stat-card">
          <strong>
            {jobs.data?.filter((job) => job.status === "processing").length ??
              "—"}
          </strong>
          <span>Jobs processing</span>
        </div>
        <div className="stat-card">
          <strong>{reviews.data?.length ?? "—"}</strong>
          <span>Open reviews</span>
        </div>
      </div>
      <div className="workspace__columns">
        <div>
          <DocumentUpload />
        </div>
        <div>
          <section className="workspace-card">
            <h2>Recent processing</h2>
            {!jobs.data?.length ? (
              <p>
                No processing jobs yet. Uploaded files are waiting for the
                processing workflow.
              </p>
            ) : (
              <ul className="plain-list">
                {jobs.data.map((job) => (
                  <li key={job.id}>
                    <Link href={`/dashboard/documents/${job.document_id}`}>
                      {label(job.stage)}
                    </Link>
                    <span>
                      {job.progress}% · {label(job.status)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="workspace-card">
            <h2>Companies</h2>
            {!companies.data?.length ? (
              <p>No company records yet.</p>
            ) : (
              <ul className="plain-list">
                {companies.data.map((company) => (
                  <li key={company.id}>
                    <Link href={`/dashboard/companies/${company.id}`}>
                      {company.name}
                    </Link>
                    <span>{company.ticker || ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="workspace-card">
            <h2>Warnings</h2>
            {!checks.data?.length ? (
              <p>No current validation warnings or failures.</p>
            ) : (
              <ul className="plain-list">
                {checks.data.map((check) => (
                  <li key={check.id}>
                    <Link href={`/dashboard/documents/${check.document_id}`}>
                      {label(check.check_name)}
                    </Link>
                    <span>{label(check.status)}</span>
                  </li>
                ))}
              </ul>
            )}
            <Link href="/dashboard/validation">
              View validation and review queue
            </Link>
          </section>
        </div>
      </div>
      <section className="workspace-card">
        <h2>Latest documents</h2>
        {!documents.data?.length ? (
          <p>No documents yet.</p>
        ) : (
          <ul className="plain-list">
            {documents.data.map((document) => (
              <li key={document.id}>
                <Link href={`/dashboard/documents/${document.id}`}>
                  {document.original_filename}
                </Link>
                <span>
                  {formatDate(document.created_at)} · {label(document.status)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <ApiHealth />
    </main>
  );
}
