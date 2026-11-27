-- Durable, privacy-preserving checkpoint for Google OAuth cleanup during account deletion.
CREATE TABLE IF NOT EXISTS private.account_deletion_oauth_states (
  user_id uuid NOT NULL REFERENCES private.account_deletion_requests(user_id) ON DELETE CASCADE,
  provider_account_hash text NOT NULL CHECK (provider_account_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('revocation_started','revoked','preserved','not_required')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, provider_account_hash)
);
ALTER TABLE private.account_deletion_oauth_states ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.account_deletion_oauth_states FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.get_account_deletion_oauth_state(
  p_user_id uuid, p_provider_account_hash text
)
RETURNS TABLE(state text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_user_id IS NULL OR p_provider_account_hash IS NULL
     OR p_provider_account_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'OAuth deletion state lookup is invalid' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
    SELECT s.state FROM private.account_deletion_oauth_states s
    WHERE s.user_id=p_user_id AND s.provider_account_hash=p_provider_account_hash;
END;
$function$;

CREATE OR REPLACE FUNCTION public.set_account_deletion_oauth_state(
  p_user_id uuid, p_provider_account_hash text, p_state text
)
RETURNS TABLE(state text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_user_id IS NULL OR p_provider_account_hash IS NULL
     OR p_provider_account_hash !~ '^[0-9a-f]{64}$'
     OR p_state NOT IN ('revocation_started','revoked','preserved','not_required') THEN
    RAISE EXCEPTION 'OAuth deletion state update is invalid' USING ERRCODE='22023';
  END IF;
  INSERT INTO private.account_deletion_oauth_states(user_id,provider_account_hash,state)
  VALUES (p_user_id,p_provider_account_hash,p_state)
  ON CONFLICT (user_id,provider_account_hash) DO UPDATE
    SET state=CASE
      WHEN private.account_deletion_oauth_states.state IN ('revoked','preserved','not_required')
        THEN private.account_deletion_oauth_states.state
      ELSE EXCLUDED.state
    END,
    updated_at=now();
  RETURN QUERY SELECT s.state FROM private.account_deletion_oauth_states s
    WHERE s.user_id=p_user_id AND s.provider_account_hash=p_provider_account_hash;
END;
$function$;

REVOKE ALL ON FUNCTION public.get_account_deletion_oauth_state(uuid,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.set_account_deletion_oauth_state(uuid,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.get_account_deletion_oauth_state(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.set_account_deletion_oauth_state(uuid,text,text) TO service_role;
