-- Durable checkpoint for user-initiated YouTube OAuth disconnects.
-- It prevents a successful provider revocation from being repeated when later
-- database cleanup (connection status, channels, or encrypted credential) must retry.
CREATE TABLE IF NOT EXISTS private.youtube_oauth_disconnect_states (
  connection_id uuid PRIMARY KEY REFERENCES public.youtube_connections(connection_id) ON DELETE CASCADE,
  state text NOT NULL CHECK (state IN ('revocation_started','revoked','preserved','not_required')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE private.youtube_oauth_disconnect_states ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.youtube_oauth_disconnect_states FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.get_youtube_disconnect_state(p_connection_id uuid)
RETURNS TABLE(state text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_connection_id IS NULL THEN
    RAISE EXCEPTION 'YouTube connection ID is required' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
    SELECT s.state FROM private.youtube_oauth_disconnect_states s
    WHERE s.connection_id=p_connection_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.set_youtube_disconnect_state(p_connection_id uuid,p_state text)
RETURNS TABLE(state text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=''
AS $function$
BEGIN
  IF COALESCE((SELECT auth.jwt()->>'role'),'') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE='42501';
  END IF;
  IF p_connection_id IS NULL OR p_state IS NULL
     OR p_state NOT IN ('revocation_started','revoked','preserved','not_required') THEN
    RAISE EXCEPTION 'YouTube disconnect state is invalid' USING ERRCODE='22023';
  END IF;
  INSERT INTO private.youtube_oauth_disconnect_states(connection_id,state)
  VALUES (p_connection_id,p_state)
  ON CONFLICT (connection_id) DO UPDATE
    SET state=CASE
      WHEN private.youtube_oauth_disconnect_states.state IN ('revoked','preserved','not_required')
        THEN private.youtube_oauth_disconnect_states.state
      ELSE EXCLUDED.state
    END,
    updated_at=now();
  RETURN QUERY SELECT s.state FROM private.youtube_oauth_disconnect_states s
    WHERE s.connection_id=p_connection_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.get_youtube_disconnect_state(uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.set_youtube_disconnect_state(uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.get_youtube_disconnect_state(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.set_youtube_disconnect_state(uuid,text) TO service_role;
