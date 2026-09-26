-- Canonical choices for the review form and database-side validation.
create table public.canonical_fields (
  statement_type text not null check (statement_type in ('income_statement', 'balance_sheet', 'cash_flow_statement')),
  machine_name text not null,
  is_core_field boolean not null default false,
  primary key (statement_type, machine_name)
);

insert into public.canonical_fields (statement_type, machine_name) values
  ('income_statement','revenue'),
  ('income_statement','cost_of_revenue'),
  ('income_statement','gross_profit'),
  ('income_statement','research_and_development'),
  ('income_statement','selling_general_administrative'),
  ('income_statement','operating_expenses'),
  ('income_statement','operating_income'),
  ('income_statement','interest_income'),
  ('income_statement','interest_expense'),
  ('income_statement','other_income_expense'),
  ('income_statement','income_before_tax'),
  ('income_statement','income_tax'),
  ('income_statement','net_income'),
  ('balance_sheet','cash_and_cash_equivalents'),
  ('balance_sheet','short_term_investments'),
  ('balance_sheet','accounts_receivable'),
  ('balance_sheet','inventory'),
  ('balance_sheet','other_current_assets'),
  ('balance_sheet','total_current_assets'),
  ('balance_sheet','property_plant_equipment'),
  ('balance_sheet','goodwill'),
  ('balance_sheet','intangible_assets'),
  ('balance_sheet','other_noncurrent_assets'),
  ('balance_sheet','total_assets'),
  ('balance_sheet','accounts_payable'),
  ('balance_sheet','short_term_debt'),
  ('balance_sheet','other_current_liabilities'),
  ('balance_sheet','total_current_liabilities'),
  ('balance_sheet','long_term_debt'),
  ('balance_sheet','other_noncurrent_liabilities'),
  ('balance_sheet','total_liabilities'),
  ('balance_sheet','common_stock'),
  ('balance_sheet','retained_earnings'),
  ('balance_sheet','accumulated_other_comprehensive_income'),
  ('balance_sheet','treasury_stock'),
  ('balance_sheet','shareholders_equity'),
  ('cash_flow_statement','net_income'),
  ('cash_flow_statement','depreciation_amortization'),
  ('cash_flow_statement','stock_based_compensation'),
  ('cash_flow_statement','change_in_receivables'),
  ('cash_flow_statement','change_in_inventory'),
  ('cash_flow_statement','change_in_payables'),
  ('cash_flow_statement','operating_cash_flow'),
  ('cash_flow_statement','capital_expenditure'),
  ('cash_flow_statement','acquisitions'),
  ('cash_flow_statement','investing_cash_flow'),
  ('cash_flow_statement','debt_issuance'),
  ('cash_flow_statement','debt_repayment'),
  ('cash_flow_statement','dividends'),
  ('cash_flow_statement','share_repurchases'),
  ('cash_flow_statement','financing_cash_flow'),
  ('cash_flow_statement','net_change_in_cash');

update public.canonical_fields set is_core_field = true
where (statement_type, machine_name) in (
  ('income_statement','revenue'),
  ('income_statement','net_income'),
  ('balance_sheet','total_assets'),
  ('balance_sheet','total_liabilities'),
  ('balance_sheet','shareholders_equity'),
  ('cash_flow_statement','operating_cash_flow'),
  ('cash_flow_statement','investing_cash_flow'),
  ('cash_flow_statement','financing_cash_flow'),
  ('cash_flow_statement','net_change_in_cash')
);

alter table public.financial_statements add column detection_confidence numeric
  check (detection_confidence between 0 and 1);

alter table public.canonical_fields enable row level security;
revoke all on public.canonical_fields from anon, authenticated;
grant select on public.canonical_fields to authenticated;
create policy canonical_fields_read on public.canonical_fields
  for select to authenticated using (true);

alter table public.line_item_mappings add column reason text;

create or replace function public.audit_mapping_review_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  source_document uuid;
  actor uuid;
  explanation text;
begin
  if tg_table_name = 'line_item_mappings' then
    select statement.document_id into source_document
      from public.financial_line_items line
      join public.financial_statements statement on statement.id = line.statement_id
      where line.id = new.line_item_id and line.user_id = new.user_id;
    actor := coalesce(new.reviewer_id, auth.uid());
    explanation := new.reason;
  else
    select statement.document_id into source_document
      from public.financial_line_items line
      join public.financial_statements statement on statement.id = line.statement_id
      where line.id = new.line_item_id and line.user_id = new.user_id;
    actor := auth.uid();
    explanation := new.review_note;
  end if;
  insert into public.audit_events (
    user_id, document_id, entity_type, entity_id, action,
    old_value, new_value, metadata
  ) values (
    new.user_id, source_document, tg_table_name, new.id,
    case when tg_op = 'INSERT' then 'created' else 'corrected' end,
    case when tg_op = 'INSERT' then null else to_jsonb(old) end,
    to_jsonb(new),
    jsonb_build_object('actor_id', actor, 'reason', explanation)
  );
  return new;
end;
$$;

revoke execute on function public.audit_mapping_review_change() from public, anon, authenticated;

create trigger line_item_mappings_audit
after insert or update on public.line_item_mappings
for each row execute function public.audit_mapping_review_change();

create trigger manual_reviews_audit
after insert or update on public.manual_reviews
for each row execute function public.audit_mapping_review_change();

create or replace function public.resolve_manual_review(
  p_review_id uuid,
  p_action text,
  p_selected_mapping text default null,
  p_reason text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor uuid := auth.uid();
  review_row public.manual_reviews%rowtype;
  statement_kind text;
  source_statement uuid;
  source_company uuid;
  source_document uuid;
begin
  if actor is null then
    raise exception 'Sign in to review a mapping' using errcode = '28000';
  end if;
  if p_action not in ('accept', 'dismiss') or p_action is null then
    raise exception 'Unknown review action' using errcode = '22023';
  end if;
  if p_reason is null or length(btrim(p_reason)) = 0 or length(p_reason) > 1000 then
    raise exception 'A review reason is required (up to 1000 characters)' using errcode = '22023';
  end if;
  select * into review_row from public.manual_reviews
    where id = p_review_id and user_id = actor and status = 'open'
    for update;
  if not found then
    raise exception 'Open review not found' using errcode = 'P0002';
  end if;
  select statement.statement_type, statement.id, statement.company_id, statement.document_id
    into statement_kind, source_statement, source_company, source_document
    from public.financial_line_items line
    join public.financial_statements statement on statement.id = line.statement_id
    where line.id = review_row.line_item_id and line.user_id = actor;
  if statement_kind is null then
    raise exception 'Review source is unavailable' using errcode = 'P0002';
  end if;
  if p_action = 'accept' then
    if not exists (
      select 1 from public.canonical_fields
      where statement_type = statement_kind and machine_name = p_selected_mapping
    ) then
      raise exception 'Choose a valid field for this statement' using errcode = '22023';
    end if;
    update public.financial_line_items set
      canonical_name = p_selected_mapping,
      review_status = 'accepted', updated_at = now()
      where id = review_row.line_item_id and user_id = actor;
    insert into public.line_item_mappings (
      user_id, line_item_id, suggested_mapping, selected_mapping,
      mapping_method, confidence, status, reviewer_id, reviewed_at, reason
    ) values (
      actor, review_row.line_item_id, review_row.suggested_mapping,
      p_selected_mapping, 'manual', 1, 'accepted', actor, now(), p_reason
    ) on conflict (line_item_id) do update set
      selected_mapping = excluded.selected_mapping,
      mapping_method = 'manual', confidence = 1, status = 'accepted',
      reviewer_id = actor, reviewed_at = now(), reason = p_reason,
      updated_at = now();
    update public.financial_statements set status = 'needs_review', updated_at = now()
      where id = source_statement and user_id = actor;
    update public.financial_metrics set is_stale = true, updated_at = now()
      where company_id = source_company and user_id = actor;
    update public.validation_results set is_stale = true, updated_at = now()
      where document_id = source_document and user_id = actor;
    update public.reports set is_stale = true, updated_at = now()
      where company_id = source_company and user_id = actor;
  end if;
  update public.manual_reviews set
    status = case when p_action = 'accept' then 'resolved' else 'dismissed' end,
    selected_mapping = case when p_action = 'accept' then p_selected_mapping else null end,
    review_note = p_reason, reviewed_at = now(), updated_at = now()
    where id = p_review_id and user_id = actor;
end;
$$;

revoke all on function public.resolve_manual_review(uuid, text, text, text) from public, anon;
grant execute on function public.resolve_manual_review(uuid, text, text, text) to authenticated;
