import Link from "next/link";
import { ApiHealth } from "../components/api-health";

export default function DashboardPage() {
  return (
    <main className="page">
      <section className="page__content">
        <p className="eyebrow">Dashboard foundation</p>
        <h1>Your analysis workspace starts here.</h1>
        <p className="description">
          The page and API connection are in place. Authentication and private
          financial data are part of the next phase, so no statements are shown
          here yet.
        </p>
        <ApiHealth />
        <Link className="button button--secondary" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
