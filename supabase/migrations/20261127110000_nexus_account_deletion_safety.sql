-- NEXUS account lifecycle safety:
-- preserve shared-workspace records when a member leaves, and provide an
-- authenticated ownership-transfer operation before an owner deletes an account.
-- This migration is committed to the Draft PR only; it is not applied to production.

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
