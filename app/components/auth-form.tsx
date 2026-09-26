"use client";

import Link from "next/link";
import { useActionState } from "react";
import { signIn, signUp } from "../auth/actions";
import { initialAuthFormState } from "../auth/form-state";

export function AuthForm({ mode }: { mode: "sign-in" | "sign-up" }) {
  const [state, action, pending] = useActionState(
    mode === "sign-in" ? signIn : signUp,
    initialAuthFormState,
  );
  const creatingAccount = mode === "sign-up";

  return (
    <div className="auth-card">
      <p className="eyebrow">Your account</p>
      <h1>{creatingAccount ? "Create an account" : "Sign in"}</h1>
      <p className="description">
        {creatingAccount
          ? "Use your email to create a private workspace for your financial documents."
          : "Access your private financial statement workspace."}
      </p>
      <form action={action} className="auth-form">
        <label htmlFor="email">Email address</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          maxLength={320}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete={creatingAccount ? "new-password" : "current-password"}
          minLength={creatingAccount ? 8 : 1}
          required
        />
        {creatingAccount && (
          <>
            <label htmlFor="confirmPassword">Confirm password</label>
            <input
              id="confirmPassword"
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
            />
          </>
        )}
        {state.message && (
          <p
            className={
              "form-message form-message--" +
              (state.status === "success" ? "success" : "error")
            }
            role={state.status === "error" ? "alert" : "status"}
          >
            {state.message}
          </p>
        )}
        <button
          className="button button--primary"
          disabled={pending}
          type="submit"
        >
          {pending
            ? "Please wait…"
            : creatingAccount
              ? "Create account"
              : "Sign in"}
        </button>
      </form>
      <p className="auth-switch">
        {creatingAccount ? "Already have an account?" : "New here?"}{" "}
        <Link href={creatingAccount ? "/login" : "/signup"}>
          {creatingAccount ? "Sign in" : "Create an account"}
        </Link>
      </p>
    </div>
  );
}
