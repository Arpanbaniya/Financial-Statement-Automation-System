import Link from "next/link";
import { requireWorkspace } from "../../../lib/require-workspace";
import { TrialBalanceWorkspace } from "../../components/trial-balance-workspace";

export default async function TrialBalancePage({
  searchParams,
}: {
  searchParams: Promise<{ document?: string }>;
}) {
  const { supabase, user } = await requireWorkspace();
  const [companies, documents] = await Promise.all([
    supabase
      .from("companies")
      .select("id,name")
      .eq("user_id", user.id)
      .order("name"),
    supabase
      .from("documents")
      .select("id,original_filename,status")
      .eq("user_id", user.id)
      .in("status", ["uploaded", "ready", "needs_review", "failed"])
      .order("created_at", { ascending: false })
      .limit(100),
  ]);
  const selected = (await searchParams).document || "";
  return (
    <main className="workspace__main tb-workspace">
      <div className="workspace__heading">
        <div>
          <p className="eyebrow">From accounts to answers</p>
          <h1>Generate your statements</h1>
          <p className="description">
            Start with an adjusted trial balance. Review the accounts, then turn
            balanced books into clear financial statements.
          </p>
        </div>
        <Link className="button button--secondary" href="/dashboard#upload">
          Upload a trial balance
        </Link>
      </div>
      <ol className="tb-pipeline" aria-label="Generation workflow">
        <li>
          <span>01</span> Upload CSV / Excel
        </li>
        <li>
          <span>02</span> Balance & map
        </li>
        <li>
          <span>03</span> Generate statements
        </li>
        <li>
          <span>04</span> Explore & export
        </li>
      </ol>
      {companies.error || documents.error ? (
        <p role="alert">Could not load your workspace. Refresh to try again.</p>
      ) : (
        <TrialBalanceWorkspace
          companies={companies.data || []}
          documents={(documents.data || []).filter((item) =>
            /\.(csv|xlsx)$/i.test(item.original_filename),
          )}
          selected={selected}
        />
      )}
    </main>
  );
}
