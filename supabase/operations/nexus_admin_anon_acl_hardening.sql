-- Privileged follow-up. Execute only as supabase_admin (or a superuser).
-- This is intentionally not a regular migration: the postgres migration role
-- cannot alter another role's default ACLs or revoke storage.objects grants.

SET ROLE supabase_admin;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM anon;

REVOKE ALL ON TABLE storage.objects FROM anon;

RESET ROLE;
