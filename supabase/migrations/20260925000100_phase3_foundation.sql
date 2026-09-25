-- Phase 3: user-owned finance schema and private document storage.

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.companies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  name text not null check (length(btrim(name)) > 0),
  ticker text,
  country text,
  industry text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id)
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  company_id uuid,
  original_filename text not null check (length(btrim(original_filename)) > 0),
  storage_path text not null,
  mime_type text not null,
  file_size bigint not null check (file_size > 0 and file_size <= 10485760),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-fA-F]{64}$'),
  status text not null default 'reserved'
    check (status in ('reserved', 'uploaded', 'processing', 'ready', 'needs_review', 'failed', 'deleting', 'delete_failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id),
  unique (user_id, storage_path),
  foreign key (company_id, user_id) references public.companies (id, user_id)
);

create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  document_id uuid not null,
  status text not null default 'queued'
    check (status in ('queued', 'processing', 'ready', 'failed')),
  stage text not null default 'queued'
    check (stage in ('queued', 'downloading', 'extracting', 'detecting_statements', 'normalizing', 'validating', 'calculating', 'ready', 'failed')),
  progress smallint not null default 0 check (progress between 0 and 100),
  error_code text,
  error_message text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (document_id, user_id) references public.documents (id, user_id) on delete cascade,
  check (finished_at is null or started_at is not null)
);

create table public.financial_statements (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  company_id uuid not null,
  document_id uuid not null,
  statement_type text not null
    check (statement_type in ('income_statement', 'balance_sheet', 'cash_flow_statement')),
  period_type text not null
    check (period_type in ('annual', 'quarterly', 'six_months', 'nine_months', 'other_duration', 'instant')),
  period_start date,
  period_end date not null,
  fiscal_year integer check (fiscal_year between 1900 and 2200),
  fiscal_quarter smallint check (fiscal_quarter between 1 and 4),
  currency text check (currency is null or currency ~ '^[A-Z]{3}$'),
  unit_scale text check (unit_scale is null or unit_scale in ('ones', 'thousands', 'millions', 'billions')),
  status text not null default 'draft'
    check (status in ('draft', 'needs_review', 'accepted', 'stale')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id),
  unique (id, document_id, user_id),
  unique (id, company_id, user_id),
  foreign key (company_id, user_id) references public.companies (id, user_id),
  foreign key (document_id, user_id) references public.documents (id, user_id) on delete cascade,
  check (period_start is null or period_start <= period_end),
  check ((period_type = 'instant' and period_start is null)
    or (period_type <> 'instant' and period_start is not null))
);

create table public.financial_line_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  statement_id uuid not null,
  canonical_name text,
  original_label text not null check (length(btrim(original_label)) > 0),
  original_value text,
  normalized_value numeric,
  original_unit text,
  currency text check (currency is null or currency ~ '^[A-Z]{3}$'),
  source_page integer check (source_page is null or source_page > 0),
  source_sheet text,
  source_cell text,
  source_table integer check (source_table is null or source_table > 0),
  extraction_method text,
  mapping_confidence numeric check (mapping_confidence between 0 and 1),
  review_status text not null default 'pending'
    check (review_status in ('pending', 'accepted', 'rejected', 'needs_review')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id),
  foreign key (statement_id, user_id) references public.financial_statements (id, user_id) on delete cascade
);

create table public.line_item_mappings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  line_item_id uuid not null,
  suggested_mapping text,
  selected_mapping text,
  mapping_method text,
  confidence numeric check (confidence between 0 and 1),
  status text not null default 'suggested'
    check (status in ('suggested', 'accepted', 'rejected', 'needs_review')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (line_item_id),
  unique (id, user_id),
  foreign key (line_item_id, user_id) references public.financial_line_items (id, user_id) on delete cascade
);

create table public.validation_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  document_id uuid not null,
  statement_id uuid,
  check_name text not null,
  status text not null check (status in ('passed', 'failed', 'warning', 'not_applicable')),
  severity text not null check (severity in ('info', 'warning', 'error')),
  expected_value numeric,
  actual_value numeric,
  difference numeric,
  message text,
  is_stale boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (document_id, user_id) references public.documents (id, user_id) on delete cascade,
  foreign key (statement_id, document_id, user_id)
    references public.financial_statements (id, document_id, user_id) on delete cascade
);

create table public.financial_metrics (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  company_id uuid not null,
  statement_id uuid,
  period_end date not null,
  metric_name text not null,
  metric_value numeric,
  formula_version text not null,
  metadata jsonb not null default '{}'::jsonb,
  is_stale boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (company_id, user_id) references public.companies (id, user_id) on delete cascade,
  foreign key (statement_id, company_id, user_id)
    references public.financial_statements (id, company_id, user_id) on delete cascade
);

create table public.manual_reviews (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  line_item_id uuid not null,
  status text not null default 'open'
    check (status in ('open', 'resolved', 'dismissed')),
  suggested_mapping text,
  selected_mapping text,
  review_note text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (line_item_id, user_id) references public.financial_line_items (id, user_id) on delete cascade
);

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  company_id uuid not null,
  document_id uuid,
  report_type text not null check (report_type in ('excel')),
  storage_path text,
  status text not null default 'queued'
    check (status in ('queued', 'generating', 'ready', 'failed')),
  is_stale boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (company_id, user_id) references public.companies (id, user_id) on delete cascade,
  foreign key (document_id, user_id) references public.documents (id, user_id) on delete cascade
);

create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  document_id uuid,
  entity_type text not null,
  entity_id uuid not null,
  action text not null,
  old_value jsonb,
  new_value jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (document_id, user_id) references public.documents (id, user_id) on delete cascade
);

create index companies_user_id_idx on public.companies (user_id);
create index documents_user_status_idx on public.documents (user_id, status, created_at desc);
create index documents_company_idx on public.documents (company_id);
create index processing_jobs_document_idx on public.processing_jobs (document_id, created_at desc);
create index financial_statements_company_period_idx
  on public.financial_statements (company_id, period_type, period_end desc);
create index financial_statements_document_idx on public.financial_statements (document_id);
create index financial_line_items_statement_idx on public.financial_line_items (statement_id);
create index financial_line_items_canonical_idx on public.financial_line_items (canonical_name);
create index line_item_mappings_user_status_idx on public.line_item_mappings (user_id, status);
create index validation_results_document_idx on public.validation_results (document_id, is_stale);
create index validation_results_statement_idx on public.validation_results (statement_id);
create index financial_metrics_company_period_idx
  on public.financial_metrics (company_id, period_end desc, metric_name);
create index manual_reviews_user_status_idx on public.manual_reviews (user_id, status);
create index manual_reviews_line_item_idx on public.manual_reviews (line_item_id);
create index reports_company_idx on public.reports (company_id, created_at desc);
create index reports_document_idx on public.reports (document_id);
create index audit_events_user_created_idx on public.audit_events (user_id, created_at desc);
create index audit_events_document_idx on public.audit_events (document_id);

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'profiles', 'companies', 'documents', 'processing_jobs',
    'financial_statements', 'financial_line_items', 'line_item_mappings',
    'validation_results', 'financial_metrics', 'manual_reviews',
    'reports', 'audit_events'
  ]
  loop
    execute format(
      'create trigger %I before update on public.%I for each row execute function public.set_updated_at()',
      table_name || '_set_updated_at', table_name
    );
  end loop;
end;
$$;

create or replace function public.create_profile_for_new_user()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.create_profile_for_new_user();

revoke all on function public.set_updated_at() from public, anon, authenticated;
revoke all on function public.create_profile_for_new_user() from public, anon, authenticated;

alter table public.profiles enable row level security;
revoke all on public.profiles from anon, authenticated;
grant select, insert, update on public.profiles to authenticated;
create policy profiles_select_own on public.profiles
  for select to authenticated using ((select auth.uid()) = id);
create policy profiles_insert_own on public.profiles
  for insert to authenticated with check ((select auth.uid()) = id);
create policy profiles_update_own on public.profiles
  for update to authenticated
  using ((select auth.uid()) = id) with check ((select auth.uid()) = id);

-- Clients can maintain their own company list.
alter table public.companies enable row level security;
revoke all on public.companies from anon, authenticated;
grant select, insert, update, delete on public.companies to authenticated;
create policy companies_select_own on public.companies
  for select to authenticated using ((select auth.uid()) = user_id);
create policy companies_insert_own on public.companies
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy companies_update_own on public.companies
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy companies_delete_own on public.companies
  for delete to authenticated using ((select auth.uid()) = user_id);

-- Documents and derived records are read-only to clients. API endpoints will
-- validate ownership and manage the workflow with server-only credentials.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'documents', 'processing_jobs', 'financial_statements',
    'financial_line_items', 'line_item_mappings', 'validation_results',
    'financial_metrics', 'manual_reviews', 'reports'
  ]
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on public.%I from anon, authenticated', table_name);
    execute format('grant select on public.%I to authenticated', table_name);
    execute format(
      'create policy %I on public.%I for select to authenticated using ((select auth.uid()) = user_id)',
      table_name || '_select_own', table_name
    );
  end loop;
end;
$$;

-- The server key bypasses RLS but still requires explicit table privileges.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'profiles', 'companies', 'documents', 'processing_jobs',
    'financial_statements', 'financial_line_items', 'line_item_mappings',
    'validation_results', 'financial_metrics', 'manual_reviews',
    'reports', 'audit_events'
  ]
  loop
    execute format('grant select, insert, update, delete on public.%I to service_role', table_name);
  end loop;
end;
$$;
alter table public.audit_events enable row level security;
revoke all on public.audit_events from anon, authenticated;
grant select on public.audit_events to authenticated;
create policy audit_events_select_own on public.audit_events
  for select to authenticated using ((select auth.uid()) = user_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'financial-documents', 'financial-documents', false, 10485760,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/csv',
    'application/csv',
    'application/vnd.ms-excel'
  ]
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- Object paths match an existing document reservation:
-- user-id/document-id/sanitized-filename.
create policy financial_documents_select_own on storage.objects
for select to authenticated
using (
  bucket_id = 'financial-documents'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1 from public.documents d
    where d.id::text = (storage.foldername(name))[2]
      and d.user_id = (select auth.uid())
      and d.storage_path = name
  )
);

create policy financial_documents_insert_reserved on storage.objects
for insert to authenticated
with check (
  bucket_id = 'financial-documents'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1 from public.documents d
    where d.id::text = (storage.foldername(name))[2]
      and d.user_id = (select auth.uid())
      and d.storage_path = name
      and d.status = 'reserved'
  )
);

create policy financial_documents_delete_own on storage.objects
for delete to authenticated
using (
  bucket_id = 'financial-documents'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and exists (
    select 1 from public.documents d
    where d.id::text = (storage.foldername(name))[2]
      and d.user_id = (select auth.uid())
      and d.storage_path = name
  )
);
