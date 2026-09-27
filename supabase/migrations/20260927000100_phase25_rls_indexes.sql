-- Keep owner-scoped RLS lookups efficient as each user's data grows.
create index if not exists processing_jobs_user_id_idx
  on public.processing_jobs (user_id);
create index if not exists financial_statements_user_id_idx
  on public.financial_statements (user_id);
create index if not exists financial_line_items_user_id_idx
  on public.financial_line_items (user_id);
create index if not exists validation_results_user_id_idx
  on public.validation_results (user_id);
create index if not exists financial_metrics_user_id_idx
  on public.financial_metrics (user_id);
create index if not exists reports_user_id_idx
  on public.reports (user_id);
create index if not exists audit_events_user_id_idx
  on public.audit_events (user_id);
