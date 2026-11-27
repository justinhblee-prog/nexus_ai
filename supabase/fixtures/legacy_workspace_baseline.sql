-- Test-only baseline for the legacy schema that existed before the first
-- NEXUS migration. This is applied only to an isolated local CI database.
-- It is not a production migration and contains no user data.

CREATE SCHEMA IF NOT EXISTS private;

CREATE TABLE IF NOT EXISTS public.workspaces (
  workspace_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.workspace_members (
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE OR REPLACE FUNCTION private.add_workspace_owner_membership()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  INSERT INTO public.workspace_members(workspace_id, user_id, role)
  VALUES (NEW.workspace_id, NEW.owner_id, 'owner')
  ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = 'owner';
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_workspace_owner_membership ON public.workspaces;
CREATE TRIGGER trg_workspace_owner_membership
AFTER INSERT ON public.workspaces
FOR EACH ROW EXECUTE FUNCTION private.add_workspace_owner_membership();

CREATE TABLE IF NOT EXISTS public.assets (
  asset_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  original_filename text NOT NULL,
  storage_key text NOT NULL UNIQUE,
  media_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  checksum_sha256 text NOT NULL,
  gltf_version text NOT NULL,
  embedded_binary boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  import_operation_key text
);

CREATE TABLE IF NOT EXISTS public.characters (
  character_id text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name text NOT NULL,
  character_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  import_operation_key text
);

CREATE TABLE IF NOT EXISTS public.character_bundle_imports (
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  operation_key text NOT NULL,
  archive_sha256 text NOT NULL,
  status text NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
  response_json jsonb,
  error_message text,
  character_id text REFERENCES public.characters(character_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id, operation_key)
);

CREATE TABLE IF NOT EXISTS public.character_assets (
  character_id text NOT NULL REFERENCES public.characters(character_id) ON DELETE CASCADE,
  asset_id text NOT NULL REFERENCES public.assets(asset_id) ON DELETE RESTRICT,
  relation text NOT NULL DEFAULT 'model',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (character_id, asset_id, relation)
);

CREATE TABLE IF NOT EXISTS public.generation_jobs (
  job_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  workspace_id text REFERENCES public.workspaces(workspace_id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'queued'
);

CREATE TABLE IF NOT EXISTS public.gallery_images (
  image_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  filename text NOT NULL,
  storage_key text NOT NULL UNIQUE,
  thumbnail_key text NOT NULL UNIQUE,
  media_type text NOT NULL,
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  checksum_sha256 text NOT NULL,
  source text NOT NULL CHECK (source IN ('user_import', 'provider_generated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  source_job_id text REFERENCES public.generation_jobs(job_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS private.generation_worker_leases (
  job_id text PRIMARY KEY REFERENCES public.generation_jobs(job_id) ON DELETE CASCADE,
  worker_id text NOT NULL,
  lease_until timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS private.generation_idempotency (
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  idempotency_key text NOT NULL,
  payload_hash text NOT NULL,
  job_id text NOT NULL REFERENCES public.generation_jobs(job_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, idempotency_key)
);

ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.characters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.character_bundle_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.character_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generation_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gallery_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.generation_worker_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.generation_idempotency ENABLE ROW LEVEL SECURITY;
