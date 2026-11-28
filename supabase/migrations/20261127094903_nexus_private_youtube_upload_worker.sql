CREATE TABLE IF NOT EXISTS private.shorts_upload_leases (
 job_id uuid PRIMARY KEY, workspace_id text NOT NULL, worker_id text NOT NULL, lease_token text NOT NULL,
 lease_until timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 provider_video_id text, verified_channel_id text, privacy_status text, last_error text,
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(workspace_id,job_id) REFERENCES public.shorts_jobs(workspace_id,job_id) ON DELETE CASCADE
);
ALTER TABLE private.shorts_upload_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.shorts_upload_leases FROM PUBLIC,anon,authenticated;

CREATE OR REPLACE FUNCTION public.claim_next_approved_shorts_job(p_worker_id text,p_lease_seconds integer DEFAULT 600,p_max_attempts integer DEFAULT 2,p_daily_limit integer DEFAULT 3)
RETURNS TABLE(job_id uuid,workspace_id text,channel_id uuid,connection_id uuid,provider_channel_id text,topic text,title text,script text,output_storage_key text,attempts integer,lease_token text,provider_video_id text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
DECLARE v_job record; v_attempts integer; v_token text;
BEGIN
 IF COALESCE(auth.jwt()->>'role','') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
 IF p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 80 OR p_lease_seconds NOT BETWEEN 60 AND 1800 OR p_max_attempts NOT BETWEEN 1 AND 3 OR p_daily_limit NOT BETWEEN 1 AND 3 THEN
  RAISE EXCEPTION 'Upload worker lease request is invalid' USING ERRCODE='22023';
 END IF;
 UPDATE public.shorts_jobs AS j SET stage='failed',updated_at=now()
 FROM private.shorts_upload_leases AS l
 WHERE l.job_id=j.job_id AND l.workspace_id=j.workspace_id AND j.stage='uploading' AND l.lease_until<=now() AND l.attempts>=p_max_attempts;
 IF (SELECT count(*) FROM public.shorts_jobs WHERE stage='published'
  AND uploaded_at >= (date_trunc('day',now() AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'America/Los_Angeles')) >= p_daily_limit THEN RETURN; END IF;
 SELECT j.job_id,j.workspace_id,j.channel_id,c.connection_id,c.provider_channel_id,j.topic,j.title,j.script,j.output_storage_key,
  COALESCE(l.attempts,0) AS attempts,l.provider_video_id
 INTO v_job
 FROM public.shorts_jobs AS j
 JOIN public.shorts_channels AS c ON c.workspace_id=j.workspace_id AND c.channel_id=j.channel_id
 JOIN public.youtube_connections AS yc ON yc.workspace_id=c.workspace_id AND yc.connection_id=c.connection_id
 LEFT JOIN private.shorts_upload_leases AS l ON l.workspace_id=j.workspace_id AND l.job_id=j.job_id
 WHERE j.stage IN ('approved','uploading') AND j.approval_status='approved' AND j.privacy_status='private'
  AND j.output_storage_key IS NOT NULL AND c.is_active=true AND c.connection_id IS NOT NULL AND yc.status='connected'
  AND (l.lease_until IS NULL OR l.lease_until<=now()) AND COALESCE(l.attempts,0)<p_max_attempts
 ORDER BY j.created_at ASC LIMIT 1 FOR UPDATE OF j SKIP LOCKED;
 IF NOT FOUND THEN RETURN; END IF;
 v_attempts:=v_job.attempts+1; v_token:=gen_random_uuid()::text;
 INSERT INTO private.shorts_upload_leases(job_id,workspace_id,worker_id,lease_token,lease_until,attempts,provider_video_id,verified_channel_id,privacy_status,last_error,updated_at)
 VALUES(v_job.job_id,v_job.workspace_id,p_worker_id,v_token,now()+make_interval(secs=>p_lease_seconds),v_attempts,v_job.provider_video_id,NULL,NULL,NULL,now())
 ON CONFLICT ON CONSTRAINT shorts_upload_leases_pkey DO UPDATE SET worker_id=EXCLUDED.worker_id,lease_token=EXCLUDED.lease_token,
 lease_until=EXCLUDED.lease_until,attempts=EXCLUDED.attempts,last_error=NULL,updated_at=now();
 UPDATE public.shorts_jobs SET stage='uploading',updated_at=now()
 WHERE shorts_jobs.job_id=v_job.job_id AND shorts_jobs.workspace_id=v_job.workspace_id;
 RETURN QUERY SELECT v_job.job_id,v_job.workspace_id,v_job.channel_id,v_job.connection_id,v_job.provider_channel_id,v_job.topic,
 v_job.title,v_job.script,v_job.output_storage_key,v_attempts,v_token,v_job.provider_video_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.heartbeat_shorts_upload_job(p_job_id uuid,p_lease_token text,p_lease_seconds integer DEFAULT 600)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
DECLARE v_rows integer;
BEGIN
 IF COALESCE(auth.jwt()->>'role','') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
 IF p_lease_seconds NOT BETWEEN 60 AND 1800 THEN RAISE EXCEPTION 'Upload heartbeat interval is invalid' USING ERRCODE='22023'; END IF;
 UPDATE private.shorts_upload_leases SET lease_until=now()+make_interval(secs=>p_lease_seconds),updated_at=now()
 WHERE job_id=p_job_id AND lease_token=p_lease_token AND lease_until>now();
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows=1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.record_shorts_upload_video_id(p_job_id uuid,p_lease_token text,p_provider_video_id text,p_verified_channel_id text,p_privacy_status text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
DECLARE v_rows integer;
BEGIN
 IF COALESCE(auth.jwt()->>'role','') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
 IF p_provider_video_id IS NULL OR p_provider_video_id='' OR p_privacy_status<>'private' THEN RAISE EXCEPTION 'YouTube upload must be verified private' USING ERRCODE='22023'; END IF;
 UPDATE private.shorts_upload_leases AS l SET provider_video_id=p_provider_video_id,verified_channel_id=p_verified_channel_id,privacy_status=p_privacy_status,updated_at=now()
 FROM public.shorts_jobs AS j JOIN public.shorts_channels AS c ON c.workspace_id=j.workspace_id AND c.channel_id=j.channel_id
 WHERE l.job_id=p_job_id AND l.lease_token=p_lease_token AND l.lease_until>now()
 AND j.job_id=l.job_id AND j.workspace_id=l.workspace_id AND c.provider_channel_id=p_verified_channel_id;
 GET DIAGNOSTICS v_rows=ROW_COUNT; RETURN v_rows=1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.finish_shorts_upload(p_job_id uuid,p_lease_token text,p_success boolean,p_provider_video_id text DEFAULT NULL,p_error text DEFAULT NULL,p_max_attempts integer DEFAULT 2)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $function$
DECLARE v_lease private.shorts_upload_leases%ROWTYPE; v_next_stage text; v_rows integer;
BEGIN
 IF COALESCE(auth.jwt()->>'role','') <> 'service_role' THEN RAISE EXCEPTION 'service_role required' USING ERRCODE='42501'; END IF;
 IF p_max_attempts NOT BETWEEN 1 AND 3 THEN RAISE EXCEPTION 'Upload retry limit is invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO v_lease FROM private.shorts_upload_leases WHERE job_id=p_job_id AND lease_token=p_lease_token AND lease_until>now() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Upload lease is missing, expired, or no longer owned' USING ERRCODE='42501'; END IF;
 IF p_success THEN
  IF p_provider_video_id IS NULL OR v_lease.provider_video_id IS DISTINCT FROM p_provider_video_id OR v_lease.privacy_status IS DISTINCT FROM 'private' THEN
   RAISE EXCEPTION 'Upload must have a verified private provider video id' USING ERRCODE='22023';
  END IF;
  UPDATE public.shorts_jobs SET stage='published',provider_video_id=p_provider_video_id,uploaded_at=now(),privacy_status='private',updated_at=now()
  WHERE job_id=p_job_id AND workspace_id=v_lease.workspace_id AND approval_status='approved' AND stage='uploading';
  GET DIAGNOSTICS v_rows=ROW_COUNT; IF v_rows<>1 THEN RAISE EXCEPTION 'Approved uploading job was not found' USING ERRCODE='42501'; END IF;
  INSERT INTO public.shorts_job_events(workspace_id,job_id,event_type,details)
  VALUES(v_lease.workspace_id,p_job_id,'upload.completed',jsonb_build_object('attempt',v_lease.attempts,'privacy_status','private'));
  UPDATE private.shorts_upload_leases SET lease_until=now(),last_error=NULL,updated_at=now() WHERE job_id=p_job_id AND lease_token=p_lease_token;
  RETURN 'published';
 END IF;
 v_next_stage:=CASE WHEN v_lease.attempts<p_max_attempts THEN 'approved' ELSE 'failed' END;
 UPDATE public.shorts_jobs SET stage=v_next_stage,updated_at=now() WHERE job_id=p_job_id AND workspace_id=v_lease.workspace_id AND stage='uploading';
 GET DIAGNOSTICS v_rows=ROW_COUNT; IF v_rows<>1 THEN RAISE EXCEPTION 'Uploading job state changed unexpectedly' USING ERRCODE='42501'; END IF;
 INSERT INTO public.shorts_job_events(workspace_id,job_id,event_type,details)
 VALUES(v_lease.workspace_id,p_job_id,'upload.failed',jsonb_build_object('attempt',v_lease.attempts,'stage',v_next_stage,'error_type',left(COALESCE(p_error,'upload_failed'),80)));
 UPDATE private.shorts_upload_leases SET lease_until=now(),last_error=left(COALESCE(p_error,'upload_failed'),250),updated_at=now() WHERE job_id=p_job_id AND lease_token=p_lease_token;
 RETURN v_next_stage;
END;
$function$;

REVOKE ALL ON FUNCTION public.claim_next_approved_shorts_job(text,integer,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.heartbeat_shorts_upload_job(uuid,text,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.record_shorts_upload_video_id(uuid,text,text,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.finish_shorts_upload(uuid,text,boolean,text,text,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_next_approved_shorts_job(text,integer,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_shorts_upload_job(uuid,text,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_shorts_upload_video_id(uuid,text,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_shorts_upload(uuid,text,boolean,text,text,integer) TO service_role;
