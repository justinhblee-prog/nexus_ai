
create table if not exists public.workspaces (
  workspace_id text primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
create table if not exists public.workspace_members (
  workspace_id text not null references public.workspaces(workspace_id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner','admin','editor','viewer')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
create table if not exists public.assets (
  asset_id text primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text not null references public.workspaces(workspace_id) on delete cascade,
  original_filename text not null,
  storage_key text not null unique,
  media_type text not null,
  size_bytes bigint not null check (size_bytes >= 0),
  checksum_sha256 text not null,
  gltf_version text not null,
  embedded_binary boolean not null default false,
  created_at timestamptz not null default now(),
  deleted_at timestamptz,
  import_operation_key text
);
create index if not exists idx_assets_import_operation on public.assets(workspace_id, owner_id, import_operation_key, deleted_at);
create index if not exists idx_assets_owner_workspace on public.assets(owner_id, workspace_id, deleted_at);
create index if not exists idx_assets_workspace on public.assets(workspace_id, deleted_at);

create table if not exists public.characters (
  character_id text primary key,
  workspace_id text not null references public.workspaces(workspace_id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  character_json jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  import_operation_key text
);
create unique index if not exists idx_characters_import_operation
  on public.characters(workspace_id, owner_id, import_operation_key) where import_operation_key is not null;
create index if not exists idx_characters_workspace on public.characters(workspace_id, deleted_at, updated_at);

create table if not exists public.character_bundle_imports (
  workspace_id text not null references public.workspaces(workspace_id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  operation_key text not null,
  archive_sha256 text not null,
  status text not null check (status in ('pending','completed','failed')),
  response_json jsonb,
  error_message text,
  character_id text references public.characters(character_id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id, operation_key)
);
create table if not exists public.character_assets (
  character_id text not null references public.characters(character_id) on delete cascade,
  asset_id text not null references public.assets(asset_id) on delete restrict,
  relation text not null default 'model',
  created_at timestamptz not null default now(),
  primary key (character_id, asset_id, relation)
);

create table if not exists public.generation_jobs (
  job_id text primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_json jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  workspace_id text references public.workspaces(workspace_id) on delete set null,
  status text not null default 'queued'
);
create index if not exists idx_generation_jobs_owner on public.generation_jobs(owner_id, updated_at desc);
create index if not exists idx_generation_jobs_workspace on public.generation_jobs(owner_id, workspace_id, updated_at desc);
create index if not exists idx_generation_jobs_owner_created on public.generation_jobs(owner_id, created_at desc, job_id desc);
create index if not exists idx_generation_jobs_workspace_created on public.generation_jobs(owner_id, workspace_id, created_at desc, job_id desc);
create index if not exists idx_generation_jobs_status_created on public.generation_jobs(status, created_at asc);
create table if not exists public.generation_worker_leases (
  job_id text primary key references public.generation_jobs(job_id) on delete cascade,
  worker_id text not null,
  lease_until timestamptz not null
);
create table if not exists public.generation_idempotency (
  owner_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null,
  payload_hash text not null,
  job_id text not null references public.generation_jobs(job_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (owner_id, idempotency_key)
);
create table if not exists public.gallery_images (
  image_id text primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  storage_key text not null unique,
  thumbnail_key text not null unique,
  media_type text not null,
  width integer not null check (width > 0),
  height integer not null check (height > 0),
  size_bytes bigint not null check (size_bytes >= 0),
  checksum_sha256 text not null,
  source text not null check (source in ('user_import','provider_generated')),
  created_at timestamptz not null default now(),
  source_job_id text references public.generation_jobs(job_id) on delete set null
);
create index if not exists idx_gallery_owner_created on public.gallery_images(owner_id, created_at desc);
create unique index if not exists idx_gallery_owner_source_job
  on public.gallery_images(owner_id, source_job_id) where source_job_id is not null;

-- Enable RLS on every table in the exposed public schema.
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.assets enable row level security;
alter table public.characters enable row level security;
alter table public.character_bundle_imports enable row level security;
alter table public.character_assets enable row level security;
alter table public.generation_jobs enable row level security;
alter table public.generation_worker_leases enable row level security;
alter table public.generation_idempotency enable row level security;
alter table public.gallery_images enable row level security;

drop policy if exists workspaces_read_member on public.workspaces;
create policy workspaces_read_member on public.workspaces for select to authenticated
using (owner_id = (select auth.uid()) or exists (
  select 1 from public.workspace_members m where m.workspace_id = workspaces.workspace_id and m.user_id = (select auth.uid())
));
drop policy if exists workspaces_create_owner on public.workspaces;
create policy workspaces_create_owner on public.workspaces for insert to authenticated
with check (owner_id = (select auth.uid()));
drop policy if exists workspaces_update_owner on public.workspaces;
create policy workspaces_update_owner on public.workspaces for update to authenticated
using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
drop policy if exists workspaces_delete_owner on public.workspaces;
create policy workspaces_delete_owner on public.workspaces for delete to authenticated
using (owner_id = (select auth.uid()));

drop policy if exists workspace_members_read_member on public.workspace_members;
create policy workspace_members_read_member on public.workspace_members for select to authenticated
using (user_id = (select auth.uid()) or exists (
  select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())
));
drop policy if exists workspace_members_owner_manage on public.workspace_members;
create policy workspace_members_owner_manage on public.workspace_members for all to authenticated
using (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())))
with check (exists (select 1 from public.workspaces w where w.workspace_id = workspace_members.workspace_id and w.owner_id = (select auth.uid())));

drop policy if exists assets_member_read on public.assets;
create policy assets_member_read on public.assets for select to authenticated
using (exists (select 1 from public.workspace_members m where m.workspace_id = assets.workspace_id and m.user_id = (select auth.uid())));
drop policy if exists assets_member_insert on public.assets;
create policy assets_member_insert on public.assets for insert to authenticated
with check (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = assets.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
drop policy if exists assets_owner_update on public.assets;
create policy assets_owner_update on public.assets for update to authenticated
using (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = assets.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')))
with check (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = assets.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
drop policy if exists assets_owner_delete on public.assets;
create policy assets_owner_delete on public.assets for delete to authenticated
using (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = assets.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));

drop policy if exists characters_member_read on public.characters;
create policy characters_member_read on public.characters for select to authenticated
using (exists (select 1 from public.workspace_members m where m.workspace_id = characters.workspace_id and m.user_id = (select auth.uid())));
drop policy if exists characters_member_insert on public.characters;
create policy characters_member_insert on public.characters for insert to authenticated
with check (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = characters.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
drop policy if exists characters_member_update on public.characters;
create policy characters_member_update on public.characters for update to authenticated
using (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = characters.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')))
with check (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = characters.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));
drop policy if exists characters_member_delete on public.characters;
create policy characters_member_delete on public.characters for delete to authenticated
using (owner_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = characters.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));

drop policy if exists bundle_imports_member_access on public.character_bundle_imports;
create policy bundle_imports_member_access on public.character_bundle_imports for all to authenticated
using (user_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = character_bundle_imports.workspace_id and m.user_id = (select auth.uid())))
with check (user_id = (select auth.uid()) and exists (select 1 from public.workspace_members m where m.workspace_id = character_bundle_imports.workspace_id and m.user_id = (select auth.uid())));

drop policy if exists character_assets_member_read on public.character_assets;
create policy character_assets_member_read on public.character_assets for select to authenticated
using (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid())));
drop policy if exists character_assets_editor_write on public.character_assets;
create policy character_assets_editor_write on public.character_assets for all to authenticated
using (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')))
with check (exists (select 1 from public.characters c join public.workspace_members m on m.workspace_id = c.workspace_id where c.character_id = character_assets.character_id and m.user_id = (select auth.uid()) and m.role in ('owner','admin','editor')));

drop policy if exists generation_jobs_owner_access on public.generation_jobs;
create policy generation_jobs_owner_access on public.generation_jobs for all to authenticated
using (owner_id = (select auth.uid()))
with check (owner_id = (select auth.uid()));
drop policy if exists gallery_images_owner_access on public.gallery_images;
create policy gallery_images_owner_access on public.gallery_images for all to authenticated
using (owner_id = (select auth.uid()))
with check (owner_id = (select auth.uid()));

-- Internal worker coordination and idempotency records are server-only.
revoke all on public.generation_worker_leases, public.generation_idempotency from anon, authenticated;
grant usage on schema public to authenticated;
grant select, insert, update, delete on public.workspaces, public.workspace_members, public.assets,
  public.characters, public.character_bundle_imports, public.character_assets,
  public.generation_jobs, public.gallery_images to authenticated;

-- Private Storage buckets. Paths must begin with the authenticated user's UUID.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('acs-assets','acs-assets',false,104857600,array['model/gltf-binary','model/gltf+json','application/octet-stream']),
  ('acs-gallery','acs-gallery',false,20971520,array['image/jpeg','image/png','image/webp']),
  ('acs-outputs','acs-outputs',false,26214400,array['image/jpeg','image/png','image/webp'])
on conflict (id) do nothing;

drop policy if exists acs_assets_select_own on storage.objects;
create policy acs_assets_select_own on storage.objects for select to authenticated
using (bucket_id = 'acs-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_assets_insert_own on storage.objects;
create policy acs_assets_insert_own on storage.objects for insert to authenticated
with check (bucket_id = 'acs-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_assets_update_own on storage.objects;
create policy acs_assets_update_own on storage.objects for update to authenticated
using (bucket_id = 'acs-assets' and (storage.foldername(name))[1] = (select auth.uid())::text)
with check (bucket_id = 'acs-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_assets_delete_own on storage.objects;
create policy acs_assets_delete_own on storage.objects for delete to authenticated
using (bucket_id = 'acs-assets' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists acs_gallery_select_own on storage.objects;
create policy acs_gallery_select_own on storage.objects for select to authenticated
using (bucket_id in ('acs-gallery','acs-outputs') and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_gallery_insert_own on storage.objects;
create policy acs_gallery_insert_own on storage.objects for insert to authenticated
with check (bucket_id in ('acs-gallery','acs-outputs') and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_gallery_update_own on storage.objects;
create policy acs_gallery_update_own on storage.objects for update to authenticated
using (bucket_id in ('acs-gallery','acs-outputs') and (storage.foldername(name))[1] = (select auth.uid())::text)
with check (bucket_id in ('acs-gallery','acs-outputs') and (storage.foldername(name))[1] = (select auth.uid())::text);
drop policy if exists acs_gallery_delete_own on storage.objects;
create policy acs_gallery_delete_own on storage.objects for delete to authenticated
using (bucket_id in ('acs-gallery','acs-outputs') and (storage.foldername(name))[1] = (select auth.uid())::text);
