-- One input configuration per private source; derived records replace atomically.
insert into public.canonical_fields(statement_type,machine_name) values
  ('balance_sheet','other_equity'),
  ('cash_flow_statement','other_working_capital'),
  ('cash_flow_statement','other_operating_adjustments'),
  ('cash_flow_statement','asset_sale_proceeds'),
  ('cash_flow_statement','other_investing_cash_flow'),
  ('cash_flow_statement','equity_issuance'),
  ('cash_flow_statement','other_financing_cash_flow'),
  ('cash_flow_statement','fx_effect'),
  ('cash_flow_statement','beginning_cash'),
  ('cash_flow_statement','ending_cash')
on conflict do nothing;
create table public.trial_balance_runs (
  document_id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  company_id uuid not null,
  settings jsonb not null,
  updated_at timestamptz not null default now(),
  foreign key (document_id, user_id) references public.documents(id,user_id) on delete cascade,
  foreign key (company_id, user_id) references public.companies(id,user_id)
);
alter table public.trial_balance_runs enable row level security;
revoke all on public.trial_balance_runs from anon, authenticated;
grant select on public.trial_balance_runs to authenticated;
grant all on public.trial_balance_runs to service_role;
create policy trial_balance_runs_read_own on public.trial_balance_runs
  for select to authenticated using ((select auth.uid()) = user_id);
create index trial_balance_runs_user_idx on public.trial_balance_runs(user_id);

create or replace function public.save_trial_balance(
  p_user_id uuid, p_document_id uuid, p_company_id uuid, p_settings jsonb,
  p_statements jsonb, p_lines jsonb, p_metrics jsonb, p_checks jsonb
) returns void language plpgsql security invoker set search_path = '' as $$
declare
  source_status text;
  item jsonb;
begin
  -- Serialize competing generations for the company and lock against deletion.
  perform 1 from public.companies where id=p_company_id and user_id=p_user_id for update;
  if not found then raise exception 'Company not found'; end if;
  select status into source_status from public.documents
    where id=p_document_id and user_id=p_user_id for update;
  if source_status is null or source_status not in ('uploaded','failed','ready','needs_review') then
    raise exception 'Document is unavailable';
  end if;
  if exists (
    select 1 from public.financial_statements s
    join jsonb_array_elements(p_statements) incoming on
      s.statement_type=incoming->>'statement_type' and s.period_end=(incoming->>'period_end')::date
    where s.user_id=p_user_id and s.company_id=p_company_id and s.document_id<>p_document_id
      and s.status='accepted' and incoming->>'status'='accepted'
  ) then raise exception 'Another accepted statement exists for this company and period'; end if;

  delete from public.financial_statements where document_id=p_document_id and user_id=p_user_id;
  delete from public.validation_results where document_id=p_document_id and user_id=p_user_id;
  for item in select value from jsonb_array_elements(p_statements) loop
    insert into public.financial_statements(id,user_id,company_id,document_id,statement_type,period_type,period_start,period_end,currency,unit_scale,status,detection_confidence)
    values ((item->>'id')::uuid,p_user_id,p_company_id,p_document_id,item->>'statement_type',item->>'period_type',
      (item->>'period_start')::date,(item->>'period_end')::date,p_settings->>'currency','ones',item->>'status',1);
  end loop;
  for item in select value from jsonb_array_elements(p_lines) loop
    insert into public.financial_line_items(id,user_id,statement_id,canonical_name,original_label,original_value,normalized_value,
      original_unit,currency,source_sheet,source_cell,extraction_method,mapping_confidence,review_status)
    values ((item->>'id')::uuid,p_user_id,(item->>'statement_id')::uuid,item->>'canonical_name',item->>'original_label',
      item->>'original_value',(item->>'normalized_value')::numeric,'ones',p_settings->>'currency',item->>'source_sheet',
      item->>'source_cell',item->>'extraction_method',1,'accepted');
  end loop;
  for item in select value from jsonb_array_elements(p_metrics) loop
    insert into public.financial_metrics(user_id,company_id,statement_id,period_end,metric_name,metric_value,formula_version,metadata)
    values(p_user_id,p_company_id,(item->>'statement_id')::uuid,(p_settings->>'period_end')::date,item->>'metric_name',
      (item->>'metric_value')::numeric,item->>'formula_version',item->'metadata');
  end loop;
  for item in select value from jsonb_array_elements(p_checks) loop
    insert into public.validation_results(user_id,document_id,check_name,status,severity,message)
    values(p_user_id,p_document_id,item->>'check_name',item->>'status',item->>'severity',item->>'message');
  end loop;
  insert into public.trial_balance_runs(document_id,user_id,company_id,settings)
    values(p_document_id,p_user_id,p_company_id,p_settings)
    on conflict(document_id) do update set company_id=excluded.company_id,settings=excluded.settings,updated_at=now();
  update public.documents set company_id=p_company_id,status='ready' where id=p_document_id and user_id=p_user_id;
  update public.reports set is_stale=true where company_id=p_company_id and user_id=p_user_id;
  insert into public.audit_events(user_id,document_id,entity_type,entity_id,action,new_value)
    values(p_user_id,p_document_id,'trial_balance',p_document_id,'generated',p_settings);
end;
$$;
revoke all on function public.save_trial_balance(uuid,uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.save_trial_balance(uuid,uuid,uuid,jsonb,jsonb,jsonb,jsonb,jsonb) to service_role;
