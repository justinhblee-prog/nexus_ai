-- Remove unnecessary anonymous SQL privileges from the NEXUS tenant data surface.
-- RLS already denies anon rows; this additionally enforces least-privilege grants.
-- The migration role is postgres, so it can change postgres-owned defaults only.
-- Supabase-admin-owned defaults require a separate privileged DBA operation.

REVOKE ALL ON TABLE
  public.workspaces,
  public.workspace_members,
  public.youtube_connections,
  public.shorts_channels,
  public.shorts_jobs,
  public.shorts_job_events,
  public.shorts_analytics_snapshots,
  public.shorts_assets,
  public.assets,
  public.character_assets,
  public.character_bundle_imports,
  public.characters,
  public.gallery_images,
  public.generation_jobs
FROM anon;

-- Keep authenticated/service_role defaults unchanged; remove only anon access
-- from objects created by the postgres migration role.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon;

