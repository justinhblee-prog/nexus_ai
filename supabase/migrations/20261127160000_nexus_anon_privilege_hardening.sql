-- Remove unnecessary anonymous SQL privileges from the NEXUS tenant data surface.
-- RLS already denies anon rows; this additionally enforces least-privilege grants
-- and prevents future public tables created by either Supabase owner role from
-- inheriting broad anon table privileges.

REVOKE ALL ON TABLE
  public.workspaces,
  public.workspace_members,
  public.youtube_connections,
  public.shorts_channels,
  public.shorts_jobs,
  public.shorts_job_events,
  public.shorts_analytics_snapshots,
  public.shorts_assets
FROM anon;

-- Supabase's live project has default table grants for both object-creator roles.
-- Keep authenticated/service_role defaults unchanged; remove only anon access.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon;
