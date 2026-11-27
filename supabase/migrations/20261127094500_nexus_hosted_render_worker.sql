-- NEXUS Phase D: tenant-safe render worker leases and private media bucket.

CREATE TABLE IF NOT EXISTS private.shorts_worker_leases (
  job_id uuid PRIMARY KEY,
  workspace_id text NOT NULL,
  worker_id text NOT NULL,
  lease_token text NOT NULL,
  lease_until timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (workspace_id, job_id)
    REFERENCES public.shorts_jobs(workspace_id, job_id)
    ON DELETE CASCADE
);

ALTER TABLE private.shorts_worker_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.shorts_worker_leases FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.claim_next_shorts_job(
  p_worker_id text,
  p_lease_seconds integer DEFAULT 600,
  p_max_attempts integer DEFAULT 3
)
RETURNS TABLE (
  job_id uuid,
  workspace_id text,
  channel_id uuid,
  topic text,
  title text,
  script text,
  channel_name text,
  persona text,
  attempts integer,
  lease_token text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_job record;
  v_attempts integer;
  v_token text;
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 80
     OR p_lease_seconds NOT BETWEEN 60 AND 1800
     OR p_max_attempts NOT BETWEEN 1 AND 5 THEN
    RAISE EXCEPTION 'Worker lease request is invalid' USING ERRCODE = '22023';
  END IF;

  UPDATE public.shorts_jobs AS j
  SET stage = 'failed', updated_at = now()
  FROM private.shorts_worker_leases AS l
  WHERE l.job_id = j.job_id
    AND l.workspace_id = j.workspace_id
    AND j.stage IN ('drafting', 'rendering', 'quality_review')
    AND l.lease_until <= now()
    AND l.attempts >= p_max_attempts;

  SELECT j.job_id, j.workspace_id, j.channel_id, j.topic, j.title, j.script,
         c.display_name AS channel_name, c.persona,
         COALESCE(l.attempts, 0) AS attempts
  INTO v_job
  FROM public.shorts_jobs AS j
  JOIN public.shorts_channels AS c
    ON c.workspace_id = j.workspace_id AND c.channel_id = j.channel_id
  LEFT JOIN private.shorts_worker_leases AS l
    ON l.workspace_id = j.workspace_id AND l.job_id = j.job_id
  WHERE j.stage IN ('queued', 'drafting', 'rendering', 'quality_review')
    AND j.approval_status = 'pending'
    AND (l.lease_until IS NULL OR l.lease_until <= now())
    AND COALESCE(l.attempts, 0) < p_max_attempts
  ORDER BY j.created_at ASC
  FOR UPDATE OF j SKIP LOCKED
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  v_attempts := v_job.attempts + 1;
  v_token := gen_random_uuid()::text;
  INSERT INTO private.shorts_worker_leases (
    job_id, workspace_id, worker_id, lease_token, lease_until, attempts, last_error, updated_at
  )
  VALUES (
    v_job.job_id, v_job.workspace_id, p_worker_id, v_token,
    now() + make_interval(secs => p_lease_seconds), v_attempts, NULL, now()
  )
  ON CONFLICT (job_id) DO UPDATE SET
    worker_id = EXCLUDED.worker_id,
    lease_token = EXCLUDED.lease_token,
    lease_until = EXCLUDED.lease_until,
    attempts = EXCLUDED.attempts,
    last_error = NULL,
    updated_at = now();

  UPDATE public.shorts_jobs
  SET stage = 'drafting', updated_at = now()
  WHERE shorts_jobs.job_id = v_job.job_id
    AND shorts_jobs.workspace_id = v_job.workspace_id;

  RETURN QUERY SELECT v_job.job_id, v_job.workspace_id, v_job.channel_id,
    v_job.topic, v_job.title, v_job.script, v_job.channel_name, v_job.persona,
    v_attempts, v_token;
END;
$function$;

CREATE OR REPLACE FUNCTION public.heartbeat_shorts_job(
  p_job_id uuid,
  p_lease_token text,
  p_lease_seconds integer DEFAULT 600
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_rows integer;
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_lease_seconds NOT BETWEEN 60 AND 1800 THEN
    RAISE EXCEPTION 'Worker heartbeat interval is invalid' USING ERRCODE = '22023';
  END IF;
  UPDATE private.shorts_worker_leases
  SET lease_until = now() + make_interval(secs => p_lease_seconds),
      updated_at = now()
  WHERE job_id = p_job_id
    AND lease_token = p_lease_token
    AND lease_until > now();
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  RETURN v_rows = 1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.finish_shorts_job(
  p_job_id uuid,
  p_lease_token text,
  p_success boolean,
  p_output_storage_key text DEFAULT NULL,
  p_title text DEFAULT NULL,
  p_script text DEFAULT NULL,
  p_error text DEFAULT NULL,
  p_max_attempts integer DEFAULT 3
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_lease private.shorts_worker_leases%ROWTYPE;
  v_next_stage text;
BEGIN
  IF COALESCE(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'service_role required' USING ERRCODE = '42501';
  END IF;
  IF p_max_attempts NOT BETWEEN 1 AND 5 THEN
    RAISE EXCEPTION 'Maximum worker attempts is invalid' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO v_lease
  FROM private.shorts_worker_leases
  WHERE job_id = p_job_id AND lease_token = p_lease_token AND lease_until > now()
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Worker lease is missing, expired, or no longer owned' USING ERRCODE = '42501';
  END IF;

  IF p_success THEN
    IF p_output_storage_key IS NULL OR p_title IS NULL OR p_script IS NULL THEN
      RAISE EXCEPTION 'Successful render requires media, title, and script' USING ERRCODE = '22023';
    END IF;
    UPDATE public.shorts_jobs
    SET stage = 'review_pending',
        output_storage_key = p_output_storage_key,
        title = p_title,
        script = p_script,
        updated_at = now()
    WHERE job_id = p_job_id AND workspace_id = v_lease.workspace_id;
    INSERT INTO public.shorts_job_events(workspace_id, job_id, event_type, details)
    VALUES (v_lease.workspace_id, p_job_id, 'render.completed',
      jsonb_build_object('attempt', v_lease.attempts, 'stage', 'review_pending'));
    UPDATE private.shorts_worker_leases
    SET lease_until = now(), last_error = NULL, updated_at = now()
    WHERE job_id = p_job_id AND lease_token = p_lease_token;
    RETURN 'review_pending';
  END IF;

  v_next_stage := CASE WHEN v_lease.attempts < p_max_attempts THEN 'queued' ELSE 'failed' END;
  UPDATE public.shorts_jobs
  SET stage = v_next_stage, updated_at = now()
  WHERE job_id = p_job_id AND workspace_id = v_lease.workspace_id;
  INSERT INTO public.shorts_job_events(workspace_id, job_id, event_type, details)
  VALUES (v_lease.workspace_id, p_job_id, 'render.failed',
    jsonb_build_object('attempt', v_lease.attempts, 'stage', v_next_stage,
                       'error_type', left(COALESCE(p_error, 'render_failed'), 80)));
  UPDATE private.shorts_worker_leases
  SET lease_until = now(), last_error = left(COALESCE(p_error, 'render_failed'), 250), updated_at = now()
  WHERE job_id = p_job_id AND lease_token = p_lease_token;
  RETURN v_next_stage;
END;
$function$;

REVOKE ALL ON FUNCTION public.claim_next_shorts_job(text,integer,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.heartbeat_shorts_job(uuid,text,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finish_shorts_job(uuid,text,boolean,text,text,text,text,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_next_shorts_job(text,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_shorts_job(uuid,text,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_shorts_job(uuid,text,boolean,text,text,text,text,integer) TO service_role;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'nexus-shorts', 'nexus-shorts', false, 104857600,
  ARRAY['video/mp4', 'image/png', 'image/jpeg', 'audio/mpeg', 'audio/wav']::text[]
)
ON CONFLICT (id) DO UPDATE SET
  public = false,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS nexus_shorts_member_read ON storage.objects;
CREATE POLICY nexus_shorts_member_read
  ON storage.objects FOR SELECT TO authenticated
  USING (
    bucket_id = 'nexus-shorts'
    AND (storage.foldername(name))[1] IS NOT NULL
    AND (SELECT private.has_workspace_role((storage.foldername(name))[1], ARRAY['owner','admin','editor','viewer']))
  );

DROP POLICY IF EXISTS nexus_shorts_editor_insert ON storage.objects;
CREATE POLICY nexus_shorts_editor_insert
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'nexus-shorts'
    AND (storage.foldername(name))[1] IS NOT NULL
    AND (SELECT private.has_workspace_role((storage.foldername(name))[1], ARRAY['owner','admin','editor']))
  );

DROP POLICY IF EXISTS nexus_shorts_editor_update ON storage.objects;
CREATE POLICY nexus_shorts_editor_update
  ON storage.objects FOR UPDATE TO authenticated
  USING (
    bucket_id = 'nexus-shorts'
    AND (SELECT private.has_workspace_role((storage.foldername(name))[1], ARRAY['owner','admin','editor']))
  )
  WITH CHECK (
    bucket_id = 'nexus-shorts'
    AND (SELECT private.has_workspace_role((storage.foldername(name))[1], ARRAY['owner','admin','editor']))
  );

DROP POLICY IF EXISTS nexus_shorts_admin_delete ON storage.objects;
CREATE POLICY nexus_shorts_admin_delete
  ON storage.objects FOR DELETE TO authenticated
  USING (
    bucket_id = 'nexus-shorts'
    AND (SELECT private.has_workspace_role((storage.foldername(name))[1], ARRAY['owner','admin']))
  );
