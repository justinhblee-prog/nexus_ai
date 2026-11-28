
-- Server-only tables intentionally have no client policies. Keep them in an unexposed schema
-- to avoid an exposed-schema RLS-without-policy finding.
create schema if not exists private;
alter table public.generation_worker_leases set schema private;
alter table public.generation_idempotency set schema private;
-- Keep foreign key references intact after moving worker coordination tables.
create index if not exists idx_workspace_members_user_role on public.workspace_members(user_id, role);
create index if not exists idx_character_assets_asset_relation on public.character_assets(asset_id, relation);
create index if not exists idx_bundle_imports_user_character on public.character_bundle_imports(user_id, character_id);
