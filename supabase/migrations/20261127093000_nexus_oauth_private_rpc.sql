-- NEXUS Phase C foundation: server-only RPC access to private OAuth state and credentials.
-- These SECURITY DEFINER functions are executable only by service_role.

ALTER TABLE private.youtube_oauth_states
  ADD COLUMN IF NOT EXISTS code_verifier text,
  ADD COLUMN IF NOT EXISTS return_uri text;

CREATE OR REPLACE FUNCTION public.store_youtube_oauth_state(
  p_state_hash text,
  p_user_id uuid,
  p_workspace_id text,
  p_provider text,
  p_redirect_uri text,
  p_return_uri text,
  p_code_verifier text,
  p_expires_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_state_hash !~ '^[0-9a-f]{64}$'
     OR p_provider <> 'youtube'
     OR p_redirect_uri !~ '^https://'
     OR p_return_uri !~ '^https://'
     OR length(p_code_verifier) NOT BETWEEN 43 AND 128
     OR p_expires_at <= now()
     OR p_expires_at > now() + interval '10 minutes' THEN
    RAISE EXCEPTION 'OAuth state payload is invalid' USING ERRCODE = '22023';
  END IF;
  INSERT INTO private.youtube_oauth_states (
    state_hash, user_id, workspace_id, provider, redirect_uri,
    return_uri, code_verifier, expires_at
  )
  VALUES (
    p_state_hash, p_user_id, p_workspace_id, p_provider, p_redirect_uri,
    p_return_uri, p_code_verifier, p_expires_at
  )
  ON CONFLICT (state_hash) DO NOTHING;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'OAuth state already exists' USING ERRCODE = '23505';
  END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION public.consume_youtube_oauth_state(p_state_hash text)
RETURNS TABLE (
  user_id uuid,
  workspace_id text,
  provider text,
  redirect_uri text,
  return_uri text,
  code_verifier text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  RETURN QUERY
  UPDATE private.youtube_oauth_states AS s
  SET consumed_at = now()
  WHERE s.state_hash = p_state_hash
    AND s.consumed_at IS NULL
    AND s.expires_at > now()
  RETURNING s.user_id, s.workspace_id, s.provider, s.redirect_uri, s.return_uri, s.code_verifier;
END;
$function$;

CREATE OR REPLACE FUNCTION public.upsert_youtube_oauth_credential(
  p_connection_id uuid,
  p_workspace_id text,
  p_encrypted_refresh_token bytea,
  p_encryption_key_version text,
  p_scopes text[],
  p_token_expires_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF octet_length(p_encrypted_refresh_token) < 28
     OR p_encryption_key_version !~ '^[A-Za-z0-9_-]{1,32}$' THEN
    RAISE EXCEPTION 'Encrypted OAuth credential is invalid' USING ERRCODE = '22023';
  END IF;
  INSERT INTO private.youtube_oauth_credentials (
    connection_id, workspace_id, encrypted_refresh_token,
    encryption_key_version, scopes, token_expires_at
  )
  VALUES (
    p_connection_id, p_workspace_id, p_encrypted_refresh_token,
    p_encryption_key_version, COALESCE(p_scopes, '{}'::text[]), p_token_expires_at
  )
  ON CONFLICT (connection_id) DO UPDATE SET
    workspace_id = EXCLUDED.workspace_id,
    encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
    encryption_key_version = EXCLUDED.encryption_key_version,
    scopes = EXCLUDED.scopes,
    token_expires_at = EXCLUDED.token_expires_at,
    updated_at = now();
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_youtube_oauth_credential(p_connection_id uuid)
RETURNS TABLE (
  workspace_id text,
  encrypted_refresh_token bytea,
  encryption_key_version text,
  scopes text[],
  token_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  RETURN QUERY
  SELECT c.workspace_id, c.encrypted_refresh_token, c.encryption_key_version,
         c.scopes, c.token_expires_at
  FROM private.youtube_oauth_credentials AS c
  WHERE c.connection_id = p_connection_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.delete_youtube_oauth_credential(p_connection_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  DELETE FROM private.youtube_oauth_credentials WHERE connection_id = p_connection_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.store_youtube_oauth_state(text,uuid,text,text,text,text,text,timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consume_youtube_oauth_state(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.upsert_youtube_oauth_credential(uuid,text,bytea,text,text[],timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_youtube_oauth_credential(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.delete_youtube_oauth_credential(uuid) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.store_youtube_oauth_state(text,uuid,text,text,text,text,text,timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_youtube_oauth_state(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.upsert_youtube_oauth_credential(uuid,text,bytea,text,text[],timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_youtube_oauth_credential(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.delete_youtube_oauth_credential(uuid) TO service_role;

CREATE INDEX IF NOT EXISTS idx_youtube_oauth_states_expiry
  ON private.youtube_oauth_states(expires_at)
  WHERE consumed_at IS NULL;
