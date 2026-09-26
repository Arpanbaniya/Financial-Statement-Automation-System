import Link from "next/link";
import { redirect } from "next/navigation";
import { signOut } from "../auth/actions";
import { ApiHealth } from "../components/api-health";
import { DocumentUpload } from "../components/document-upload";
import { createClient } from "../../lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: profile } = await supabase
    .from("profiles")
    .select("display_name")
    .eq("id", user.id)
    .maybeSingle();
  const { error } = await searchParams;

  return (
    <main className="page">
      <section className="page__content">
        <p className="eyebrow">Private workspace</p>
        <h1>Welcome to your dashboard.</h1>
        <p className="description">
          Signed in as <strong>{profile?.display_name || user.email}</strong>.
          Your profile and documents belong to this account.
        </p>
        {error === "signout" && (
          <p className="form-message form-message--error" role="alert">
            We could not sign you out. Please try again.
          </p>
        )}
        <div className="actions">
          <form action={signOut}>
            <button className="button button--primary" type="submit">
              Sign out
            </button>
          </form>
          <Link className="button button--secondary" href="/">
            Back to home
          </Link>
        </div>
        <DocumentUpload />
        <ApiHealth />
      </section>
    </main>
  );
}
