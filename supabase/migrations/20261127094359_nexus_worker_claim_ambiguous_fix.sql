CREATE OR REPLACE FUNCTION public.claim_next_shorts_job(
  p_worker_id text,
  p_lease_seconds integer DEFAULT 600,
  p_max_attempts integer DEFAULT 3
)
RETURNS TABLE (
  job_id uuid, workspace_id text, channel_id uuid, topic text, title text,
  script text, channel_name text, persona text, attempts integer, lease_token text
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
         c.display_name AS channel_name, c.persona, COALESCE(l.attempts, 0) AS attempts
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
  LIMIT 1
  FOR UPDATE OF j SKIP LOCKED;

  IF NOT FOUND THEN RETURN; END IF;
  v_attempts := v_job.attempts + 1;
  v_token := gen_random_uuid()::text;

  INSERT INTO private.shorts_worker_leases (
    job_id, workspace_id, worker_id, lease_token, lease_until, attempts, last_error, updated_at
  )
  VALUES (
    v_job.job_id, v_job.workspace_id, p_worker_id, v_token,
    now() + make_interval(secs => p_lease_seconds), v_attempts, NULL, now()
  )
  ON CONFLICT ON CONSTRAINT shorts_worker_leases_pkey DO UPDATE SET
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

  RETURN QUERY SELECT v_job.job_id, v_job.workspace_id, v_job.channel_id, v_job.topic,
    v_job.title, v_job.script, v_job.channel_name, v_job.persona, v_attempts, v_token;
END;
$function$;
REVOKE ALL ON FUNCTION public.claim_next_shorts_job(text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_next_shorts_job(text, integer, integer) TO service_role;
