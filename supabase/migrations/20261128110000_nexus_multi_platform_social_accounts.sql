-- NEXUS: expand the provider-neutral social account model without changing
-- existing YouTube data, worker contracts, or tenant ownership boundaries.
-- The legacy physical table names are retained for backwards compatibility.

ALTER TABLE public.youtube_connections
  DROP CONSTRAINT IF EXISTS youtube_connections_provider_check;
ALTER TABLE public.youtube_connections
  ADD CONSTRAINT youtube_connections_provider_check
  CHECK (provider IN ('youtube', 'tiktok', 'instagram', 'facebook', 'linkedin'));

ALTER TABLE public.shorts_channels
  DROP CONSTRAINT IF EXISTS shorts_channels_platform_check;
ALTER TABLE public.shorts_channels
  ADD CONSTRAINT shorts_channels_platform_check
  CHECK (platform IN ('youtube', 'tiktok', 'instagram', 'facebook', 'linkedin'));

ALTER TABLE private.youtube_oauth_states
  DROP CONSTRAINT IF EXISTS youtube_oauth_states_provider_check;
ALTER TABLE private.youtube_oauth_states
  ADD CONSTRAINT youtube_oauth_states_provider_check
  CHECK (provider IN ('youtube', 'tiktok', 'instagram', 'facebook', 'linkedin'));

COMMENT ON TABLE public.youtube_connections IS
  'Legacy physical name; stores provider-neutral social account connections scoped to a NEXUS workspace.';
COMMENT ON COLUMN public.youtube_connections.provider IS
  'Social provider key: youtube, tiktok, instagram, facebook, or linkedin.';
COMMENT ON TABLE public.shorts_channels IS
  'Provider-neutral publishing destinations discovered from connected social accounts; workspace scoped.';
COMMENT ON TABLE private.youtube_oauth_credentials IS
  'Legacy physical name; encrypted provider refresh credentials keyed by social connection ID.';
COMMENT ON TABLE private.youtube_oauth_states IS
  'Legacy physical name; one-time OAuth state for supported social providers.';

CREATE INDEX IF NOT EXISTS idx_youtube_connections_workspace_provider_status
  ON public.youtube_connections (workspace_id, provider, status);
CREATE INDEX IF NOT EXISTS idx_shorts_channels_workspace_platform_active
  ON public.shorts_channels (workspace_id, platform, is_active);

-- The existing RPC remains server-only. Permit only the explicitly supported
-- provider identifiers; provider adapters still have to be implemented and
-- enabled separately before a user can initiate their OAuth flow.
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
     OR p_provider NOT IN ('youtube', 'tiktok', 'instagram', 'facebook', 'linkedin')
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

REVOKE ALL ON FUNCTION public.store_youtube_oauth_state(text,uuid,text,text,text,text,text,timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.store_youtube_oauth_state(text,uuid,text,text,text,text,text,timestamptz)
  TO service_role;
