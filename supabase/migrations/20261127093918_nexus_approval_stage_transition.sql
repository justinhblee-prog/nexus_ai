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
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$function$;
REVOKE ALL ON FUNCTION private.guard_shorts_job_approval() FROM PUBLIC, anon, authenticated;
