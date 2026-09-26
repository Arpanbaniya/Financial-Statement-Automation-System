import Link from "next/link";

export default function LoginPage() {
  return (
    <main className="page">
      <section className="page__content">
        <p className="eyebrow">Account access</p>
        <h1>Sign in is coming next.</h1>
        <p className="description">
          This route is ready for Supabase authentication. Account creation,
          sign-in, and private sessions will be added in the next phase.
        </p>
        <Link className="button button--secondary" href="/">
          Back to home
        </Link>
      </section>
    </main>
  );
}
