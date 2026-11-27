-- NEXUS Phase A: Supabase Auth identity bootstrap and workspace RLS hardening.
-- Safe for the selected single-project Free Plan deployment; no paid extensions or services.

ALTER TABLE public.workspaces
  ADD COLUMN IF NOT EXISTS workspace_name text NOT NULL DEFAULT 'My Workspace';

CREATE TABLE IF NOT EXISTS public.profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.profiles FROM anon, authenticated;
GRANT SELECT, UPDATE ON TABLE public.profiles TO authenticated;

DROP POLICY IF EXISTS profiles_select_self ON public.profiles;
CREATE POLICY profiles_select_self
  ON public.profiles FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = id);

DROP POLICY IF EXISTS profiles_update_self ON public.profiles;
CREATE POLICY profiles_update_self
  ON public.profiles FOR UPDATE TO authenticated
  USING ((SELECT auth.uid()) = id)
  WITH CHECK ((SELECT auth.uid()) = id);

-- Avoid recursive RLS evaluation between workspaces and workspace_members.
-- This narrowly-scoped helper is private, checks auth.uid() internally, and
-- accepts only a workspace identifier (never a caller-supplied user identifier).
CREATE OR REPLACE FUNCTION private.is_workspace_owner(p_workspace_id text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspaces AS w
    WHERE w.workspace_id = p_workspace_id
      AND w.owner_id = (SELECT auth.uid())
  );
$function$;

REVOKE ALL ON FUNCTION private.is_workspace_owner(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.is_workspace_owner(text) TO authenticated;

DROP POLICY IF EXISTS workspace_members_read_member ON public.workspace_members;
CREATE POLICY workspace_members_read_member
  ON public.workspace_members FOR SELECT TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    OR (SELECT private.is_workspace_owner(workspace_id))
  );

DROP POLICY IF EXISTS workspace_members_owner_insert ON public.workspace_members;
CREATE POLICY workspace_members_owner_insert
  ON public.workspace_members FOR INSERT TO authenticated
  WITH CHECK ((SELECT private.is_workspace_owner(workspace_id)));

DROP POLICY IF EXISTS workspace_members_owner_update ON public.workspace_members;
CREATE POLICY workspace_members_owner_update
  ON public.workspace_members FOR UPDATE TO authenticated
  USING ((SELECT private.is_workspace_owner(workspace_id)))
  WITH CHECK ((SELECT private.is_workspace_owner(workspace_id)));

DROP POLICY IF EXISTS workspace_members_owner_delete ON public.workspace_members;
CREATE POLICY workspace_members_owner_delete
  ON public.workspace_members FOR DELETE TO authenticated
  USING ((SELECT private.is_workspace_owner(workspace_id)));

CREATE OR REPLACE FUNCTION private.bootstrap_nexus_auth_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_display_name text;
  v_workspace_id text;
BEGIN
  v_display_name := NULLIF(
    BTRIM(COALESCE(NEW.raw_user_meta_data ->> 'full_name',
                   NEW.raw_user_meta_data ->> 'name', '')),
    ''
  );

  INSERT INTO public.profiles (id, display_name)
  VALUES (NEW.id, v_display_name)
  ON CONFLICT (id) DO NOTHING;

  v_workspace_id := 'wsp_' || gen_random_uuid()::text;
  INSERT INTO public.workspaces (workspace_id, owner_id, workspace_name)
  VALUES (v_workspace_id, NEW.id, 'My Workspace');

  -- Existing trg_workspace_owner_membership inserts the owner membership.
  RETURN NEW;
END;
$function$;

REVOKE ALL ON FUNCTION private.bootstrap_nexus_auth_user() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS on_auth_user_created_nexus_workspace ON auth.users;
CREATE TRIGGER on_auth_user_created_nexus_workspace
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION private.bootstrap_nexus_auth_user();

CREATE INDEX IF NOT EXISTS idx_workspace_members_user_workspace
  ON public.workspace_members (user_id, workspace_id);
