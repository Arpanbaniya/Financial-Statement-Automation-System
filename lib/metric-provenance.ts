type SourceStatement = {
  id: string;
  document_id: string;
  currency?: string | null;
  period_type?: string;
};

function sourceRefs(
  metadata: unknown,
): { statement_id: string; line_item_id: string }[] {
  if (!metadata || typeof metadata !== "object" || !("source_refs" in metadata))
    return [];
  const refs = metadata.source_refs;
  if (!Array.isArray(refs) || !refs.length) return [];
  if (
    !refs.every(
      (ref) =>
        ref &&
        typeof ref.statement_id === "string" &&
        typeof ref.line_item_id === "string",
    )
  )
    return [];
  return refs;
}

export function metricSourceLinks(
  metadata: unknown,
  statements: Map<string, SourceStatement>,
): { href: string; label: string }[] {
  const refs = sourceRefs(metadata);
  if (!refs.length) return [];
  const links: { href: string; label: string }[] = [];
  for (const ref of refs) {
    const statement = statements.get(ref.statement_id);
    if (!statement) return [];
    const href = `/dashboard/documents/${statement.document_id}#line-${ref.line_item_id}`;
    if (links.some((item) => item.href === href)) continue;
    links.push({ href, label: `Source line ${links.length + 1}` });
  }
  return links;
}

export function metricSourceCurrency(
  metadata: unknown,
  statements: Map<string, SourceStatement>,
): string | null {
  const refs = sourceRefs(metadata);
  if (!refs.length) return null;
  const currencies = new Set(
    refs.map((ref) => statements.get(ref.statement_id)?.currency),
  );
  return currencies.size === 1 ? [...currencies][0] || null : null;
}

export function metricPrimaryPeriodType(
  statementId: string | null,
  metadata: unknown,
  statements: Map<string, SourceStatement>,
): string | null {
  const primary = statementId || sourceRefs(metadata)[0]?.statement_id;
  return primary ? statements.get(primary)?.period_type || null : null;
}
