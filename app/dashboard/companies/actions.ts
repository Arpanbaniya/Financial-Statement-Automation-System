"use server";

import { revalidatePath } from "next/cache";
import { requireWorkspace } from "../../../lib/require-workspace";

export async function createCompany(formData: FormData) {
  const name = String(formData.get("name") || "").trim();
  const ticker = String(formData.get("ticker") || "")
    .trim()
    .toUpperCase();
  if (!name || name.length > 120 || ticker.length > 12) return;
  const { supabase, user } = await requireWorkspace();
  const { error } = await supabase
    .from("companies")
    .insert({ user_id: user.id, name, ticker: ticker || null });
  if (error) throw new Error("Company could not be saved.");
  revalidatePath("/dashboard/companies");
  revalidatePath("/dashboard");
}
