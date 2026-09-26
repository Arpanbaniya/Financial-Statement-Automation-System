"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireWorkspace } from "../../../lib/require-workspace";

export async function resolveReview(formData: FormData) {
  const { supabase } = await requireWorkspace();
  const reviewId = String(formData.get("review_id") || "");
  const action = String(formData.get("action") || "");
  const selected = String(formData.get("selected_mapping") || "");
  const reason = String(formData.get("reason") || "").trim();
  if (
    !/^[0-9a-f-]{36}$/i.test(reviewId) ||
    !["accept", "dismiss"].includes(action) ||
    !reason ||
    reason.length > 1000 ||
    (action === "accept" && !selected)
  ) {
    redirect("/dashboard/validation?result=invalid");
  }
  const { error } = await supabase.rpc("resolve_manual_review", {
    p_review_id: reviewId,
    p_action: action,
    p_selected_mapping: action === "accept" ? selected : null,
    p_reason: reason,
  });
  if (error) redirect("/dashboard/validation?result=failed");
  revalidatePath("/dashboard/validation");
  revalidatePath("/dashboard/analysis");
  revalidatePath("/dashboard");
  redirect("/dashboard/validation?result=saved");
}
