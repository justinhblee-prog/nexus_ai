-- NEXUS Phase B: workspace-scoped Shorts domain, OAuth metadata, and private credential vault.
-- All new client-facing tables use RLS; refresh tokens and OAuth state stay in private schema.

CREATE OR REPLACE FUNCTION private.has_workspace_role(
  p_workspace_id text,
  p_allowed_roles text[]
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspace_members AS wm
    WHERE wm.workspace_id = p_workspace_id
      AND wm.user_id = (SELECT auth.uid())
      AND wm.role = ANY (p_allowed_roles)
  );
$function$;

REVOKE ALL ON FUNCTION private.has_workspace_role(text, text[]) FROM PUBLIC, anon;
GRANT USAGE ON SCHEMA private TO authenticated;
GRANT EXECUTE ON FUNCTION private.has_workspace_role(text, text[]) TO authenticated;

CREATE TABLE IF NOT EXISTS public.youtube_connections (
  connection_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('youtube', 'tiktok')),
  provider_account_id text NOT NULL,
  display_name text NOT NULL,
  status text NOT NULL DEFAULT 'connected'
    CHECK (status IN ('connected', 'reauth_required', 'disconnected')),
  scopes text[] NOT NULL DEFAULT '{}'::text[],
  connected_by uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  disconnected_at timestamptz,
  UNIQUE (workspace_id, connection_id),
  UNIQUE (workspace_id, provider, provider_account_id)
);

CREATE TABLE IF NOT EXISTS public.shorts_channels (
  channel_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  connection_id uuid,
  platform text NOT NULL CHECK (platform IN ('youtube', 'tiktok')),
  provider_channel_id text NOT NULL,
  display_name text NOT NULL,
  persona text NOT NULL DEFAULT '전문가 톤',
  is_active boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, channel_id),
  UNIQUE (workspace_id, platform, provider_channel_id),
  FOREIGN KEY (workspace_id, connection_id)
    REFERENCES public.youtube_connections(workspace_id, connection_id)
    ON DELETE SET NULL (connection_id)
);

CREATE TABLE IF NOT EXISTS public.shorts_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  channel_id uuid NOT NULL,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  topic text NOT NULL,
  title text NOT NULL DEFAULT '',
  script text NOT NULL DEFAULT '',
  output_storage_key text,
  stage text NOT NULL DEFAULT 'queued'
    CHECK (stage IN ('queued', 'drafting', 'rendering', 'quality_review', 'review_pending', 'approved', 'uploading', 'published', 'failed', 'cancelled')),
  approval_status text NOT NULL DEFAULT 'pending'
    CHECK (approval_status IN ('pending', 'approved', 'rejected')),
  privacy_status text NOT NULL DEFAULT 'private'
    CHECK (privacy_status = 'private'),
  provider_video_id text,
  approved_by uuid REFERENCES auth.users(id),
  approved_at timestamptz,
  uploaded_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, job_id),
  FOREIGN KEY (workspace_id, channel_id)
    REFERENCES public.shorts_channels(workspace_id, channel_id)
    ON DELETE RESTRICT,
  CHECK (
    (approval_status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
    OR (approval_status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS public.shorts_job_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL,
  job_id uuid NOT NULL,
  actor_id uuid REFERENCES auth.users(id),
  event_type text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (workspace_id, job_id)
    REFERENCES public.shorts_jobs(workspace_id, job_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.shorts_analytics_snapshots (
  snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL,
  channel_id uuid NOT NULL,
  period text NOT NULL CHECK (period IN ('day', 'week', 'month')),
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (workspace_id, channel_id)
    REFERENCES public.shorts_channels(workspace_id, channel_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.shorts_assets (
  asset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  asset_kind text NOT NULL CHECK (asset_kind IN ('source_video', 'rendered_video', 'thumbnail', 'audio', 'image')),
  storage_key text NOT NULL UNIQUE,
  media_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  checksum_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

-- Credentials are encrypted by the application before insertion. This schema is
-- intentionally not exposed to PostgREST and has no client policies or grants.
CREATE TABLE IF NOT EXISTS private.youtube_oauth_credentials (
  connection_id uuid PRIMARY KEY,
  workspace_id text NOT NULL,
  encrypted_refresh_token bytea NOT NULL,
  encryption_key_version text NOT NULL,
  scopes text[] NOT NULL DEFAULT '{}'::text[],
  token_expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (workspace_id, connection_id)
    REFERENCES public.youtube_connections(workspace_id, connection_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS private.youtube_oauth_states (
  state_hash text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id text NOT NULL REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('youtube', 'tiktok')),
  redirect_uri text NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.youtube_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shorts_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shorts_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shorts_job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shorts_analytics_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shorts_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.youtube_oauth_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.youtube_oauth_states ENABLE ROW LEVEL SECURITY;

GRANT SELECT ON public.youtube_connections, public.shorts_channels, public.shorts_jobs,
  public.shorts_job_events, public.shorts_analytics_snapshots, public.shorts_assets
  TO authenticated;
GRANT INSERT (workspace_id, provider, provider_account_id, display_name, scopes, connected_by)
  ON public.youtube_connections TO authenticated;
GRANT UPDATE (status, scopes, disconnected_at, updated_at, display_name)
  ON public.youtube_connections TO authenticated;
GRANT DELETE ON public.youtube_connections TO authenticated;
GRANT INSERT (workspace_id, connection_id, platform, provider_channel_id, display_name, persona, created_by)
  ON public.shorts_channels TO authenticated;
GRANT UPDATE (display_name, persona, is_active, updated_at)
  ON public.shorts_channels TO authenticated;
GRANT DELETE ON public.shorts_channels TO authenticated;
GRANT INSERT (workspace_id, channel_id, created_by, topic, title, script)
  ON public.shorts_jobs TO authenticated;
GRANT UPDATE (topic, title, script, updated_at, approval_status, approved_by, approved_at)
  ON public.shorts_jobs TO authenticated;
GRANT DELETE ON public.shorts_jobs TO authenticated;
GRANT INSERT (workspace_id, job_id, actor_id, event_type, details)
  ON public.shorts_job_events TO authenticated;
GRANT INSERT (workspace_id, created_by, asset_kind, storage_key, media_type, size_bytes, checksum_sha256)
  ON public.shorts_assets TO authenticated;
GRANT UPDATE (deleted_at) ON public.shorts_assets TO authenticated;
GRANT DELETE ON public.shorts_assets TO authenticated;
REVOKE ALL ON TABLE private.youtube_oauth_credentials, private.youtube_oauth_states FROM PUBLIC, anon, authenticated;

CREATE POLICY youtube_connections_member_read
  ON public.youtube_connections FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));
CREATE POLICY youtube_connections_admin_insert
  ON public.youtube_connections FOR INSERT TO authenticated
  WITH CHECK (
    connected_by = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin']))
  );
CREATE POLICY youtube_connections_admin_update
  ON public.youtube_connections FOR UPDATE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])))
  WITH CHECK ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])));
CREATE POLICY youtube_connections_admin_delete
  ON public.youtube_connections FOR DELETE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])));

CREATE POLICY shorts_channels_member_read
  ON public.shorts_channels FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));
CREATE POLICY shorts_channels_editor_insert
  ON public.shorts_channels FOR INSERT TO authenticated
  WITH CHECK (
    created_by = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor']))
  );
CREATE POLICY shorts_channels_editor_update
  ON public.shorts_channels FOR UPDATE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])))
  WITH CHECK ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])));
CREATE POLICY shorts_channels_admin_delete
  ON public.shorts_channels FOR DELETE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])));

CREATE POLICY shorts_jobs_member_read
  ON public.shorts_jobs FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));
CREATE POLICY shorts_jobs_editor_insert
  ON public.shorts_jobs FOR INSERT TO authenticated
  WITH CHECK (
    created_by = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor']))
  );
CREATE POLICY shorts_jobs_editor_update
  ON public.shorts_jobs FOR UPDATE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])))
  WITH CHECK ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])));
CREATE POLICY shorts_jobs_admin_delete
  ON public.shorts_jobs FOR DELETE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])));

CREATE POLICY shorts_job_events_member_read
  ON public.shorts_job_events FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));
CREATE POLICY shorts_job_events_editor_insert
  ON public.shorts_job_events FOR INSERT TO authenticated
  WITH CHECK (
    actor_id = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor']))
  );

CREATE POLICY shorts_analytics_member_read
  ON public.shorts_analytics_snapshots FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));

CREATE POLICY shorts_assets_member_read
  ON public.shorts_assets FOR SELECT TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor','viewer'])));
CREATE POLICY shorts_assets_editor_insert
  ON public.shorts_assets FOR INSERT TO authenticated
  WITH CHECK (
    created_by = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor']))
  );
CREATE POLICY shorts_assets_editor_update
  ON public.shorts_assets FOR UPDATE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])))
  WITH CHECK ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin','editor'])));
CREATE POLICY shorts_assets_admin_delete
  ON public.shorts_assets FOR DELETE TO authenticated
  USING ((SELECT private.has_workspace_role(workspace_id, ARRAY['owner','admin'])));

CREATE OR REPLACE FUNCTION private.guard_shorts_job_approval()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
  IF NEW.approval_status IS DISTINCT FROM OLD.approval_status
     OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
     OR NEW.approved_at IS DISTINCT FROM OLD.approved_at THEN
    IF NOT (SELECT private.has_workspace_role(NEW.workspace_id, ARRAY['owner','admin'])) THEN
      RAISE EXCEPTION 'Only workspace owners or admins may approve Shorts jobs'
        USING ERRCODE = '42501';
    END IF;
    IF NEW.approval_status = 'approved'
       AND (NEW.approved_by IS DISTINCT FROM (SELECT auth.uid()) OR NEW.approved_at IS NULL) THEN
      RAISE EXCEPTION 'Approval must be attributed to the authenticated reviewer'
        USING ERRCODE = '42501';
    END IF;
    IF NEW.approval_status <> 'approved' THEN
      NEW.approved_by := NULL;
      NEW.approved_at := NULL;
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION private.guard_shorts_job_approval() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER shorts_jobs_approval_guard
  BEFORE UPDATE ON public.shorts_jobs
  FOR EACH ROW EXECUTE FUNCTION private.guard_shorts_job_approval();

CREATE INDEX IF NOT EXISTS idx_shorts_channels_workspace_created
  ON public.shorts_channels(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_jobs_workspace_created
  ON public.shorts_jobs(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_jobs_workspace_stage
  ON public.shorts_jobs(workspace_id, stage);
CREATE INDEX IF NOT EXISTS idx_shorts_job_events_workspace_created
  ON public.shorts_job_events(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_analytics_workspace_channel
  ON public.shorts_analytics_snapshots(workspace_id, channel_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_shorts_assets_workspace_created
  ON public.shorts_assets(workspace_id, created_at DESC);
