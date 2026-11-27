
-- Workspace creators automatically become owners/members; callers cannot spoof the owner.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
create or replace function private.add_workspace_owner_membership()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.workspace_members(workspace_id, user_id, role)
  values (new.workspace_id, new.owner_id, 'owner')
  on conflict (workspace_id, user_id) do update set role = 'owner';
  return new;
end;
$$;
revoke all on function private.add_workspace_owner_membership() from public, anon, authenticated;
drop trigger if exists trg_workspace_owner_membership on public.workspaces;
create trigger trg_workspace_owner_membership
after insert on public.workspaces
for each row execute function private.add_workspace_owner_membership();

-- Avoid duplicate permissive policies while preserving member read and owner administration.
drop policy if exists workspace_members_owner_manage on public.workspace_members;
create policy workspace_members_owner_insert on public.workspace_members for insert to authenticated
with check (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())));
create policy workspace_members_owner_update on public.workspace_members for update to authenticated
using (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())))
with check (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())));
create policy workspace_members_owner_delete on public.workspace_members for delete to authenticated
using (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())));

drop policy if exists character_assets_editor_write on public.character_assets;
create policy character_assets_editor_insert on public.character_assets for insert to authenticated
with check (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
create policy character_assets_editor_update on public.character_assets for update to authenticated
using (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')))
with check (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
create policy character_assets_editor_delete on public.character_assets for delete to authenticated
using (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));

-- Cover all foreign keys used for joins/deletes.
create index if not exists idx_workspaces_owner on public.workspaces(owner_id);
create index if not exists idx_workspace_members_user on public.workspace_members(user_id);
create index if not exists idx_assets_owner on public.assets(owner_id);
create index if not exists idx_characters_owner on public.characters(owner_id);
create index if not exists idx_bundle_imports_user on public.character_bundle_imports(user_id);
create index if not exists idx_bundle_imports_character on public.character_bundle_imports(character_id);
create index if not exists idx_character_assets_asset on public.character_assets(asset_id);
create index if not exists idx_generation_jobs_workspace_fk on public.generation_jobs(workspace_id);
create index if not exists idx_generation_idempotency_job on public.generation_idempotency(job_id);
create index if not exists idx_gallery_source_job on public.gallery_images(source_job_id);
