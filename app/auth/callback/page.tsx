"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "../../../lib/supabase/client";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    const supabase = createClient();

    async function finishSignIn() {
      const {
        data: { user },
        error: authError,
      } = await supabase.auth.getUser();

      if (!active) return;

      if (user && !authError) {
        window.history.replaceState(null, "", "/auth/callback");
        router.replace("/dashboard");
        router.refresh();
      } else {
        window.history.replaceState(null, "", "/auth/callback");
        setError(true);
      }
    }

    void finishSignIn();
    return () => {
      active = false;
    };
  }, [router]);

  return (
    <main className="page page--auth">
      <div className="auth-card" aria-live="polite">
        <p className="eyebrow">Email confirmation</p>
        <h1>{error ? "Continue with your password" : "Finishing sign in…"}</h1>
        <p className="description">
          {error
            ? "If your email was confirmed, sign in to continue. If the link expired, create an account again."
            : "We are checking your confirmation link and opening your workspace."}
        </p>
        {error && (
          <Link className="button button--secondary" href="/login">
            Back to sign in
          </Link>
        )}
      </div>
    </main>
  );
}
