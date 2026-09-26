import Link from "next/link";
import { ApiHealth } from "./components/api-health";

export default function HomePage() {
  return (
    <main className="page">
      <section className="page__content">
        <p className="eyebrow">Financial Statement Automation System</p>
        <h1>Know where every number came from.</h1>
        <p className="description">
          A workspace for turning financial documents into checked, traceable
          statements and analysis. Private accounts and uploads are available;
          analysis appears as documents are processed.
        </p>
        <div className="actions">
          <Link className="button button--primary" href="/dashboard">
            View dashboard
          </Link>
          <Link className="button button--secondary" href="/login">
            Sign in
          </Link>
        </div>
        <ApiHealth />
      </section>
    </main>
  );
}
