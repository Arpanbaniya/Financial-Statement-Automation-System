import { createClient } from "./supabase/client";

export async function authenticatedRequest(
  path: string,
  method = "GET",
  body?: object,
) {
  const { data } = await createClient().auth.getSession();
  if (!data.session) throw new Error("Your session expired. Sign in again.");
  const response = await fetch(path, {
    method,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${data.session.access_token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return response;
}

export function apiError(result: { detail?: unknown; issues?: string[] }) {
  if (result.issues?.length) return result.issues.join("; ");
  if (typeof result.detail === "string") return result.detail;
  if (Array.isArray(result.detail))
    return result.detail
      .map(
        (issue: { loc?: string[]; msg?: string }) =>
          `${issue.loc?.at(-1) || "Field"}: ${issue.msg || "Invalid value"}`,
      )
      .join("; ");
  return "Request failed. Please try again.";
}
