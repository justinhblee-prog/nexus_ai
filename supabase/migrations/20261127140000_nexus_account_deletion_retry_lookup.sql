-- Safe retry lookup for an account deletion request whose tombstone already exists.
-- This does not create or mutate a request and is callable only by service_role.
CREATE OR REPLACE FUNCTION public.get_account_deletion_request(p_user_id uuid)
RETURNS TABLE(status text, phase text, attempt_count integer, sessions_revoked boolean)
LANGUAGE plpgsql
STABLE
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
  RETURN QUERY
  SELECT r.status, r.phase, r.attempt_count, r.sessions_revoked
  FROM private.account_deletion_requests AS r
  WHERE r.user_id = p_user_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.get_account_deletion_request(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_account_deletion_request(uuid) TO service_role;
