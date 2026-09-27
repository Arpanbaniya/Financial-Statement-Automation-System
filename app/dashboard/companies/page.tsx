import Link from "next/link";
import { requireWorkspace } from "../../../lib/require-workspace";
import { createCompany } from "./actions";

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
      <section className="workspace-card">
        <h2>Add a company</h2>
        <form
          action={createCompany}
          className="metadata-form metadata-form--compact"
        >
          <label>
            Company name
            <input
              name="name"
              required
              maxLength={120}
              placeholder="Example Company"
            />
          </label>
          <label>
            Ticker <span>(optional)</span>
            <input name="ticker" maxLength={12} placeholder="EXM" />
          </label>
          <button className="button button--primary" type="submit">
            Add company
          </button>
        </form>
      </section>
      {error ? (
        <p role="alert">Companies could not be loaded. Try refreshing.</p>
      ) : !data?.length ? (
        <section className="workspace-card">
          <p>
            No company records yet. Add one above to organize your statements.
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
