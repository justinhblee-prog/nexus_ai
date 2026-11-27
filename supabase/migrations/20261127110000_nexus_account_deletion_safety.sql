-- NEXUS account lifecycle safety:
-- preserve shared-workspace records when a member leaves, and provide an
-- authenticated ownership-transfer operation before an owner deletes an account.
-- This migration is committed to the Draft PR only; it is not applied to production.

-- Preserve shared legacy workspace content while removing personal authorship.
ALTER TABLE public.assets ALTER COLUMN owner_id DROP NOT NULL;
ALTER TABLE public.characters ALTER COLUMN owner_id DROP NOT NULL;
ALTER TABLE public.generation_jobs ALTER COLUMN owner_id DROP NOT NULL;
ALTER TABLE public.character_bundle_imports ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE public.youtube_connections
  ALTER COLUMN connected_by DROP NOT NULL;
ALTER TABLE public.youtube_connections
  DROP CONSTRAINT IF EXISTS youtube_connections_connected_by_fkey;
ALTER TABLE public.youtube_connections
  ADD CONSTRAINT youtube_connections_connected_by_fkey
  FOREIGN KEY (connected_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.shorts_channels
  ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE public.shorts_channels
  DROP CONSTRAINT IF EXISTS shorts_channels_created_by_fkey;
ALTER TABLE public.shorts_channels
  ADD CONSTRAINT shorts_channels_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.shorts_jobs
  ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE public.shorts_jobs
  DROP CONSTRAINT IF EXISTS shorts_jobs_created_by_fkey;
ALTER TABLE public.shorts_jobs
  ADD CONSTRAINT shorts_jobs_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.shorts_assets
  ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE public.shorts_assets
  DROP CONSTRAINT IF EXISTS shorts_assets_created_by_fkey;
ALTER TABLE public.shorts_assets
  ADD CONSTRAINT shorts_assets_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.shorts_job_events
  DROP CONSTRAINT IF EXISTS shorts_job_events_actor_id_fkey;
ALTER TABLE public.shorts_job_events
  ADD CONSTRAINT shorts_job_events_actor_id_fkey
  FOREIGN KEY (actor_id) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.shorts_jobs
  DROP CONSTRAINT IF EXISTS shorts_jobs_approved_by_fkey;
ALTER TABLE public.shorts_jobs
  ADD CONSTRAINT shorts_jobs_approved_by_fkey
  FOREIGN KEY (approved_by) REFERENCES auth.users(id) ON DELETE SET NULL;

-- Keep the approval timestamp and approved state when the reviewer account is
-- removed; the attribution FK becomes NULL, while the approval guard still
-- enforces the reviewer identity at the moment approval is granted.
ALTER TABLE public.shorts_jobs
  DROP CONSTRAINT IF EXISTS shorts_jobs_check;
ALTER TABLE public.shorts_jobs
  ADD CONSTRAINT shorts_jobs_check CHECK (
    (approval_status = 'approved' AND approved_at IS NOT NULL)
    OR
    (approval_status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
  );

CREATE OR REPLACE FUNCTION public.transfer_workspace_ownership(
  p_workspace_id text,
  p_new_owner_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_current_owner uuid;
BEGIN
  IF (SELECT auth.uid()) IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  IF p_workspace_id IS NULL
     OR p_workspace_id !~ '^wsp_[0-9a-fA-F-]{36}$'
     OR p_new_owner_id IS NULL
     OR p_new_owner_id = (SELECT auth.uid()) THEN
    RAISE EXCEPTION 'Ownership transfer request is invalid' USING ERRCODE = '22023';
  END IF;

  SELECT w.owner_id
    INTO v_current_owner
  FROM public.workspaces AS w
  WHERE w.workspace_id = p_workspace_id
  FOR UPDATE;

  IF NOT FOUND OR v_current_owner <> (SELECT auth.uid()) THEN
    RAISE EXCEPTION 'Workspace owner permission required' USING ERRCODE = '42501';
  END IF;

  PERFORM 1
  FROM public.workspace_members AS wm
  WHERE wm.workspace_id = p_workspace_id
    AND wm.user_id = p_new_owner_id
    AND wm.role = 'admin'
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'New owner must already be an admin member' USING ERRCODE = '22023';
  END IF;

  UPDATE public.workspaces
  SET owner_id = p_new_owner_id
  WHERE workspace_id = p_workspace_id;

  UPDATE public.workspace_members
  SET role = CASE
    WHEN user_id = p_new_owner_id THEN 'owner'
    WHEN user_id = v_current_owner THEN 'admin'
    ELSE role
  END
  WHERE workspace_id = p_workspace_id
    AND user_id IN (v_current_owner, p_new_owner_id);
END;
$function$;

REVOKE ALL ON FUNCTION public.transfer_workspace_ownership(text, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.transfer_workspace_ownership(text, uuid) TO authenticated;

-- The FK action for approved_by runs without an end-user JWT. Permit only
-- this exact anonymization transition; ordinary authenticated approval changes
-- continue through the existing owner/admin and reviewer-attribution guard.
CREATE OR REPLACE FUNCTION private.guard_shorts_job_approval()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
  IF (SELECT auth.uid()) IS NULL
     AND current_user IN ('postgres', 'supabase_auth_admin', 'service_role')
     AND OLD.approval_status = 'approved'
     AND NEW.approval_status = 'approved'
     AND OLD.approved_by IS NOT NULL
     AND NEW.approved_by IS NULL
     AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at
     AND NEW.stage IS NOT DISTINCT FROM OLD.stage THEN
    NEW.updated_at := now();
    RETURN NEW;
  END IF;

  IF NEW.approval_status IS DISTINCT FROM OLD.approval_status
     OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
     OR NEW.approved_at IS DISTINCT FROM OLD.approved_at THEN
    IF OLD.stage IN ('uploading', 'published') THEN
      RAISE EXCEPTION 'Approval cannot be changed after private YouTube upload has started'
        USING ERRCODE = '42501';
    END IF;
    IF NOT (SELECT private.has_workspace_role(NEW.workspace_id, ARRAY['owner','admin'])) THEN
      RAISE EXCEPTION 'Only workspace owners or admins may approve Shorts jobs'
        USING ERRCODE = '42501';
    END IF;
    IF NEW.approval_status = 'approved' THEN
      IF NEW.approved_by IS DISTINCT FROM (SELECT auth.uid()) OR NEW.approved_at IS NULL THEN
        RAISE EXCEPTION 'Approval must be attributed to the authenticated reviewer'
          USING ERRCODE = '42501';
      END IF;
      NEW.stage := 'approved';
    ELSIF NEW.approval_status = 'rejected' THEN
      NEW.approved_by := NULL;
      NEW.approved_at := NULL;
      NEW.stage := 'cancelled';
    ELSIF NEW.approval_status = 'pending' THEN
      NEW.approved_by := NULL;
      NEW.approved_at := NULL;
      NEW.stage := 'review_pending';
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION private.guard_shorts_job_approval() FROM PUBLIC, anon, authenticated;

-- Enumerate account-owned objects without exposing storage.objects to clients.
-- Actual bytes are always removed via the Supabase Storage API, not SQL.
CREATE OR REPLACE FUNCTION public.list_account_deletion_storage_objects(
  p_user_id uuid,
  p_limit integer DEFAULT 1000,
  p_offset integer DEFAULT 0,
  p_workspace_ids text[] DEFAULT ARRAY[]::text[]
)
RETURNS TABLE(bucket_id text, name text, owner_id text, owner text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_user_id IS NULL OR p_limit NOT BETWEEN 1 AND 1000 OR p_offset < 0
     OR p_workspace_ids IS NULL OR cardinality(p_workspace_ids) > 100
     OR EXISTS (
       SELECT 1 FROM unnest(p_workspace_ids) AS item(workspace_id)
       WHERE item.workspace_id !~ '^wsp_[0-9a-fA-F-]{36}$'
     ) THEN
    RAISE EXCEPTION 'Storage enumeration request is invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT o.bucket_id, o.name, o.owner_id, o.owner::text
  FROM storage.objects AS o
  WHERE o.owner = p_user_id
     OR o.owner_id = p_user_id::text
     OR split_part(o.name, '/', 1) = ANY(p_workspace_ids)
     OR EXISTS (
       SELECT 1 FROM public.gallery_images AS gi
       WHERE gi.owner_id = p_user_id
         AND o.name IN (gi.storage_key, gi.thumbnail_key)
     )
  ORDER BY o.bucket_id, o.name
  LIMIT p_limit OFFSET p_offset;
END;
$function$;

REVOKE ALL ON FUNCTION public.list_account_deletion_storage_objects(uuid,integer,integer,text[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_account_deletion_storage_objects(uuid,integer,integer,text[]) TO service_role;

-- Identify active hosted render/upload leases for workspaces that are safe to
-- delete. Account cleanup must wait rather than race a worker or private upload.
CREATE OR REPLACE FUNCTION public.list_account_deletion_active_leases(
  p_workspace_ids text[]
)
RETURNS TABLE(workspace_id text, job_id uuid, lease_kind text, lease_until timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_workspace_ids IS NULL OR cardinality(p_workspace_ids) > 100 THEN
    RAISE EXCEPTION 'Workspace lease inventory request is invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT l.workspace_id, l.job_id, 'render'::text, l.lease_until
  FROM private.shorts_worker_leases AS l
  WHERE l.workspace_id = ANY(p_workspace_ids) AND l.lease_until > now()
  UNION ALL
  SELECT l.workspace_id, l.job_id, 'upload'::text, l.lease_until
  FROM private.shorts_upload_leases AS l
  WHERE l.workspace_id = ANY(p_workspace_ids) AND l.lease_until > now()
  ORDER BY 4;
END;
$function$;

REVOKE ALL ON FUNCTION public.list_account_deletion_active_leases(text[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_account_deletion_active_leases(text[]) TO service_role;

-- Persistent tombstones survive auth.users deletion and invalidate otherwise
-- still-unexpired access JWTs at the hosted API boundary.
CREATE TABLE IF NOT EXISTS private.account_deletion_tombstones (
  user_id uuid PRIMARY KEY,
  tombstoned_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE private.account_deletion_tombstones ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.account_deletion_tombstones FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.mark_account_deletion_tombstone(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_user_id IS NULL THEN
    RAISE EXCEPTION 'User ID is required' USING ERRCODE = '22023';
  END IF;
  INSERT INTO private.account_deletion_tombstones(user_id)
  VALUES (p_user_id)
  ON CONFLICT (user_id) DO NOTHING;
END;
$function$;

CREATE OR REPLACE FUNCTION public.is_account_deletion_tombstoned()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_user_id uuid;
BEGIN
  v_user_id := (SELECT auth.uid());
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM private.account_deletion_tombstones AS t
    WHERE t.user_id = v_user_id
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.mark_account_deletion_tombstone(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_account_deletion_tombstone(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.is_account_deletion_tombstoned() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_account_deletion_tombstoned() TO authenticated;

CREATE TABLE IF NOT EXISTS private.account_deletion_requests (
  user_id uuid PRIMARY KEY,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','retry','blocked','completed','failed')),
  phase text NOT NULL DEFAULT 'queued',
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_until timestamptz,
  preflight_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(preflight_snapshot) = 'object'),
  last_error_code text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
ALTER TABLE private.account_deletion_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.account_deletion_requests FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.enqueue_account_deletion(p_user_id uuid,p_preflight_snapshot jsonb)
RETURNS TABLE(status text,phase text,attempt_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_user_id IS NULL OR p_preflight_snapshot IS NULL OR jsonb_typeof(p_preflight_snapshot) <> 'object' THEN
    RAISE EXCEPTION 'Account deletion request is invalid' USING ERRCODE = '22023';
  END IF;
  INSERT INTO private.account_deletion_tombstones(user_id) VALUES (p_user_id) ON CONFLICT (user_id) DO NOTHING;
  INSERT INTO private.account_deletion_requests(user_id,preflight_snapshot) VALUES (p_user_id,p_preflight_snapshot)
  ON CONFLICT (user_id) DO NOTHING;
  RETURN QUERY SELECT r.status,r.phase,r.attempt_count FROM private.account_deletion_requests r WHERE r.user_id=p_user_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.claim_next_account_deletion_request(p_worker_id text,p_lease_seconds integer DEFAULT 180)
RETURNS TABLE(user_id uuid,status text,phase text,attempt_count integer,preflight_snapshot jsonb,lease_until timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
  IF p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 128 OR p_lease_seconds NOT BETWEEN 30 AND 900 THEN
    RAISE EXCEPTION 'Account deletion worker lease is invalid' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
  WITH candidate AS (
    SELECT r.user_id FROM private.account_deletion_requests r
    WHERE (r.status IN ('pending','retry') AND r.next_attempt_at <= now())
       OR (r.status='running' AND r.lease_until < now())
    ORDER BY r.requested_at FOR UPDATE SKIP LOCKED LIMIT 1
  )
  UPDATE private.account_deletion_requests r
  SET status='running',phase=CASE WHEN r.status='running' THEN r.phase ELSE 'claimed' END,
      attempt_count=r.attempt_count+1,lease_owner=p_worker_id,
      lease_until=now()+make_interval(secs=>p_lease_seconds),updated_at=now()
  FROM candidate c WHERE r.user_id=c.user_id
  RETURNING r.user_id,r.status,r.phase,r.attempt_count,r.preflight_snapshot,r.lease_until;
END;
$function$;

CREATE OR REPLACE FUNCTION public.update_account_deletion_request(
 p_user_id uuid,p_worker_id text,p_status text,p_phase text,p_error_code text DEFAULT NULL,p_retry_seconds integer DEFAULT 60
)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
 IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
 IF p_user_id IS NULL OR p_worker_id IS NULL OR p_status NOT IN ('retry','blocked','completed','failed')
    OR p_phase IS NULL OR length(p_phase) NOT BETWEEN 1 AND 64 OR p_retry_seconds NOT BETWEEN 5 AND 86400
    OR (p_error_code IS NOT NULL AND length(p_error_code)>64) THEN
   RAISE EXCEPTION 'Account deletion update is invalid' USING ERRCODE='22023';
 END IF;
 UPDATE private.account_deletion_requests
 SET status=p_status,phase=p_phase,last_error_code=p_error_code,
     next_attempt_at=CASE WHEN p_status='retry' THEN now()+make_interval(secs=>p_retry_seconds) ELSE next_attempt_at END,
     lease_owner=NULL,lease_until=NULL,updated_at=now(),
     completed_at=CASE WHEN p_status='completed' THEN now() ELSE NULL END
 WHERE user_id=p_user_id AND status='running' AND lease_owner=p_worker_id;
 RETURN FOUND;
END;
$function$;


CREATE OR REPLACE FUNCTION public.delete_account_deletion_private_user_rows(p_user_id uuid)
RETURNS TABLE(idempotency_rows integer,oauth_state_rows integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_user_id IS NULL THEN RAISE EXCEPTION 'User ID is required' USING ERRCODE='22023'; END IF;
  DELETE FROM private.generation_idempotency WHERE owner_id=p_user_id;
  GET DIAGNOSTICS idempotency_rows = ROW_COUNT;
  DELETE FROM private.youtube_oauth_states WHERE user_id=p_user_id;
  GET DIAGNOSTICS oauth_state_rows = ROW_COUNT;
  RETURN NEXT;
END;
$function$;

CREATE OR REPLACE FUNCTION public.count_account_deletion_private_user_rows(p_user_id uuid)
RETURNS TABLE(idempotency_rows bigint,oauth_state_rows bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_user_id IS NULL THEN RAISE EXCEPTION 'User ID is required' USING ERRCODE='22023'; END IF;
  RETURN QUERY SELECT
    (SELECT count(*) FROM private.generation_idempotency WHERE owner_id=p_user_id),
    (SELECT count(*) FROM private.youtube_oauth_states WHERE user_id=p_user_id);
END;
$function$;

REVOKE ALL ON FUNCTION public.delete_account_deletion_private_user_rows(uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.count_account_deletion_private_user_rows(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.delete_account_deletion_private_user_rows(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.count_account_deletion_private_user_rows(uuid) TO service_role;

REVOKE ALL ON FUNCTION public.enqueue_account_deletion(uuid,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.claim_next_account_deletion_request(text,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.update_account_deletion_request(uuid,text,text,text,text,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_account_deletion(uuid,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_next_account_deletion_request(text,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.update_account_deletion_request(uuid,text,text,text,text,integer) TO service_role;


     ) THEN
    RAISE EXCEPTION 'Storage enumeration request is invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT o.bucket_id, o.name, o.owner_id, o.owner::text
  FROM storage.objects AS o
  WHERE o.owner = p_user_id
     OR o.owner_id = p_user_id::text
     OR split_part(o.name, '/', 1) = ANY(p_workspace_ids)
  ORDER BY o.bucket_id, o.name
  LIMIT p_limit OFFSET p_offset;
END;
$function$;

REVOKE ALL ON FUNCTION public.list_account_deletion_storage_objects(uuid,integer,integer,text[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_account_deletion_storage_objects(uuid,integer,integer,text[]) TO service_role;

-- Identify active hosted render/upload leases for workspaces that are safe to
-- delete. Account cleanup must wait rather than race a worker or private upload.
CREATE OR REPLACE FUNCTION public.list_account_deletion_active_leases(
  p_workspace_ids text[]
)
RETURNS TABLE(workspace_id text, job_id uuid, lease_kind text, lease_until timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_workspace_ids IS NULL OR cardinality(p_workspace_ids) > 100 THEN
    RAISE EXCEPTION 'Workspace lease inventory request is invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT l.workspace_id, l.job_id, 'render'::text, l.lease_until
  FROM private.shorts_worker_leases AS l
  WHERE l.workspace_id = ANY(p_workspace_ids) AND l.lease_until > now()
  UNION ALL
  SELECT l.workspace_id, l.job_id, 'upload'::text, l.lease_until
  FROM private.shorts_upload_leases AS l
  WHERE l.workspace_id = ANY(p_workspace_ids) AND l.lease_until > now()
  ORDER BY 4;
END;
$function$;

REVOKE ALL ON FUNCTION public.list_account_deletion_active_leases(text[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_account_deletion_active_leases(text[]) TO service_role;

-- Persistent tombstones survive auth.users deletion and invalidate otherwise
-- still-unexpired access JWTs at the hosted API boundary.
CREATE TABLE IF NOT EXISTS private.account_deletion_tombstones (
  user_id uuid PRIMARY KEY,
  tombstoned_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE private.account_deletion_tombstones ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.account_deletion_tombstones FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.mark_account_deletion_tombstone(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt() ->> 'role'), '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_user_id IS NULL THEN
    RAISE EXCEPTION 'User ID is required' USING ERRCODE = '22023';
  END IF;
  INSERT INTO private.account_deletion_tombstones(user_id)
  VALUES (p_user_id)
  ON CONFLICT (user_id) DO NOTHING;
END;
$function$;

CREATE OR REPLACE FUNCTION public.is_account_deletion_tombstoned()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_user_id uuid;
BEGIN
  v_user_id := (SELECT auth.uid());
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  RETURN EXISTS (
    SELECT 1 FROM private.account_deletion_tombstones AS t
    WHERE t.user_id = v_user_id
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.mark_account_deletion_tombstone(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_account_deletion_tombstone(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.is_account_deletion_tombstoned() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_account_deletion_tombstoned() TO authenticated;
