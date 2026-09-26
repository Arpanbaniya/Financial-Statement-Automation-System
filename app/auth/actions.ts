"use server";

import type { AuthError } from "@supabase/supabase-js";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "../../lib/supabase/server";
import type { AuthFormState } from "./form-state";

function errorState(message: string): AuthFormState {
  return { status: "error", message };
}

function authErrorMessage(error: AuthError): string {
  switch (error.code) {
    case "invalid_credentials":
      return "That email and password do not match an account.";
    case "email_not_confirmed":
      return "Confirm your email using the link we sent before signing in.";
    case "user_already_exists":
      return "An account already uses this email. Try signing in.";
    case "weak_password":
      return "Choose a stronger password and try again.";
    case "email_address_invalid":
      return "Enter a valid email address.";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "Too many attempts. Please wait a little and try again.";
    case "signup_disabled":
      return "Account creation is currently unavailable.";
    default:
      return "We could not complete that request. Please try again.";
  }
}

function readCredentials(
  formData: FormData,
  minimumPasswordLength: number,
):
  | { valid: true; email: string; password: string }
  | { valid: false; error: string } {
  const email = formData.get("email");
  const password = formData.get("password");

  if (
    typeof email !== "string" ||
    email.length > 320 ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
  ) {
    return { valid: false, error: "Enter a valid email address." };
  }

  if (typeof password !== "string" || password.length < minimumPasswordLength) {
    return {
      valid: false,
      error:
        minimumPasswordLength === 1
          ? "Enter your password."
          : "Use a password with at least 8 characters.",
    };
  }

  return { valid: true, email: email.trim(), password };
}

export async function signIn(
  _previousState: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const credentials = readCredentials(formData, 1);
  if (!credentials.valid) {
    return errorState(credentials.error);
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email: credentials.email,
    password: credentials.password,
  });
  if (error) {
    return errorState(authErrorMessage(error));
  }

  revalidatePath("/dashboard");
  redirect("/dashboard");
}

export async function signUp(
  _previousState: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const credentials = readCredentials(formData, 8);
  if (!credentials.valid) {
    return errorState(credentials.error);
  }

  if (formData.get("confirmPassword") !== credentials.password) {
    return errorState("The passwords do not match.");
  }

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;
  if (!siteUrl) {
    return errorState("Account creation is temporarily unavailable.");
  }

  const supabase = await createClient();
  const { data, error } = await supabase.auth.signUp({
    email: credentials.email,
    password: credentials.password,
    options: {
      emailRedirectTo: new URL("/auth/callback", siteUrl).toString(),
    },
  });
  if (error) {
    return errorState(authErrorMessage(error));
  }

  if (data.session) {
    revalidatePath("/dashboard");
    redirect("/dashboard");
  }

  return {
    status: "success",
    message: "Check your email for a confirmation link, then sign in.",
  };
}

export async function signOut() {
  const supabase = await createClient();
  const { error } = await supabase.auth.signOut();
  if (error) {
    redirect("/dashboard?error=signout");
  }

  revalidatePath("/dashboard");
  redirect("/login");
}
