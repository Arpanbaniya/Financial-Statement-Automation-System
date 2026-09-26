-- The source label and location remain on financial_line_items. The mapping row
-- stores the decision; reviewers and review times complete its audit metadata.
alter table public.line_item_mappings
  add column reviewer_id uuid references public.profiles (id) on delete set null,
  add column reviewed_at timestamptz;
