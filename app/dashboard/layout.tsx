import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { createClient } from "../../lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  return (
    <div className="workspace">
      <nav className="workspace__nav" aria-label="Workspace navigation">
        <Link href="/dashboard">Overview</Link>
        <Link href="/dashboard/companies">Companies</Link>
        <Link href="/dashboard/analysis">Analysis</Link>
        <Link href="/dashboard/validation">Validation</Link>
        <Link href="/dashboard/reports">Reports</Link>
      </nav>
      {children}
    </div>
  );
}
