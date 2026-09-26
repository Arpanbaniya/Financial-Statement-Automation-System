import { redirect } from "next/navigation";
import { createClient } from "./supabase/server";

export async function requireWorkspace() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  return { supabase, user };
}
