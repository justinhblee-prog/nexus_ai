-- Cover every foreign key reported by the live NEXUS schema advisor.
-- These indexes keep tenant/workspace cleanup and parent-row updates bounded.
CREATE INDEX IF NOT EXISTS idx_shorts_upload_leases_workspace_job_fk
  ON private.shorts_upload_leases (workspace_id, job_id);
CREATE INDEX IF NOT EXISTS idx_shorts_worker_leases_workspace_job_fk
  ON private.shorts_worker_leases (workspace_id, job_id);
CREATE INDEX IF NOT EXISTS idx_youtube_oauth_credentials_workspace_connection_fk
  ON private.youtube_oauth_credentials (workspace_id, connection_id);
CREATE INDEX IF NOT EXISTS idx_youtube_oauth_states_user_fk
  ON private.youtube_oauth_states (user_id);
CREATE INDEX IF NOT EXISTS idx_youtube_oauth_states_workspace_fk
  ON private.youtube_oauth_states (workspace_id);
CREATE INDEX IF NOT EXISTS idx_shorts_assets_created_by_fk
  ON public.shorts_assets (created_by);
CREATE INDEX IF NOT EXISTS idx_shorts_channels_created_by_fk
  ON public.shorts_channels (created_by);
CREATE INDEX IF NOT EXISTS idx_shorts_channels_workspace_connection_fk
  ON public.shorts_channels (workspace_id, connection_id);
CREATE INDEX IF NOT EXISTS idx_shorts_job_events_actor_fk
  ON public.shorts_job_events (actor_id);
CREATE INDEX IF NOT EXISTS idx_shorts_job_events_workspace_job_fk
  ON public.shorts_job_events (workspace_id, job_id);
CREATE INDEX IF NOT EXISTS idx_shorts_jobs_approved_by_fk
  ON public.shorts_jobs (approved_by);
CREATE INDEX IF NOT EXISTS idx_shorts_jobs_created_by_fk
  ON public.shorts_jobs (created_by);
CREATE INDEX IF NOT EXISTS idx_shorts_jobs_workspace_channel_fk
  ON public.shorts_jobs (workspace_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_youtube_connections_connected_by_fk
  ON public.youtube_connections (connected_by);
