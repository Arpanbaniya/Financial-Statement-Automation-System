import Link from "next/link";
import { requireWorkspace } from "../../../lib/require-workspace";

export default async function CompaniesPage() {
  const { supabase, user } = await requireWorkspace();
  const { data, error } = await supabase
    .from("companies")
    .select("id,name,ticker,country,industry")
    .eq("user_id", user.id)
    .order("name");
  return (
    <main className="workspace__main">
      <p className="eyebrow">Company records</p>
      <h1>Companies</h1>
      {error ? (
        <p role="alert">Companies could not be loaded. Try refreshing.</p>
      ) : !data?.length ? (
        <section className="workspace-card">
          <p>
            No companies have been created yet. Uploaded documents are not
            assigned to a company until processing is connected.
          </p>
        </section>
      ) : (
        <div className="card-grid">
          {data.map((company) => (
            <section className="workspace-card" key={company.id}>
              <h2>
                <Link href={`/dashboard/companies/${company.id}`}>
                  {company.name}
                </Link>
              </h2>
              <p>
                {[company.ticker, company.country, company.industry]
                  .filter(Boolean)
                  .join(" · ") || "No profile details yet"}
              </p>
            </section>
          ))}
        </div>
      )}
    </main>
  );
}
