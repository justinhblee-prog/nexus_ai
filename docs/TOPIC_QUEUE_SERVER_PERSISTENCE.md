# NEXUS server-persisted topic queue — migration handoff

Status: **application/API/UI implemented; timestamped migration artifact is present on this PR branch; local validation and live application are pending**.

The server queue is deliberately separate from `shorts_jobs`. It is a personal saved-topic list scoped to both the authenticated user and the selected workspace. It is never consumed by a render or upload worker.

## Migration artifact and local validation

The migration filename `20261127143658_nexus_user_workspace_topic_queue.sql` was assigned by the Supabase CLI during the local attempt. That attempt created an empty file under the user home directory rather than the project checkout. The populated SQL artifact is now present on this PR branch at the CLI-assigned timestamp. Do not create a second timestamped migration or rename this file. Before any live application, sync this branch into the intended local checkout and run local validation:

```powershell
supabase --version
supabase db lint --local
```

Run the local lint only after the intended local Supabase stack is running. Do not run `supabase db push` against the live project as part of this validation.

Confirm the populated file matches the SQL below, run local database validation and security advisors, and verify RLS behavior with two users before considering activation. This PR does not apply the migration to the active Supabase project.

## SQL

```sql
CREATE TABLE IF NOT EXISTS public.shorts_topic_queue (
  topic_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id text NOT NULL
    REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE,
  user_id uuid NOT NULL
    REFERENCES auth.users(id) ON DELETE CASCADE,
  topic text NOT NULL
    CHECK (char_length(btrim(topic)) BETWEEN 1 AND 300),
  normalized_topic text GENERATED ALWAYS AS (
    lower(regexp_replace(btrim(topic), '\s+', ' ', 'g'))
  ) STORED,
  source text NOT NULL DEFAULT 'manual'
    CHECK (source IN ('manual', 'trend_radar')),
  region text NOT NULL DEFAULT ''
    CHECK (char_length(region) <= 12),
  source_name text NOT NULL DEFAULT ''
    CHECK (char_length(source_name) <= 120),
  source_url text
    CHECK (source_url IS NULL OR source_url ~ '^https://'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, user_id, normalized_topic)
);

CREATE INDEX IF NOT EXISTS idx_shorts_topic_queue_user_recent
  ON public.shorts_topic_queue
  (workspace_id, user_id, created_at DESC, topic_id DESC);

ALTER TABLE public.shorts_topic_queue ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.shorts_topic_queue FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.shorts_topic_queue TO authenticated;

CREATE POLICY shorts_topic_queue_member_read
  ON public.shorts_topic_queue FOR SELECT TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(
      workspace_id, ARRAY['owner','admin','editor','viewer']
    ))
  );

CREATE POLICY shorts_topic_queue_member_insert
  ON public.shorts_topic_queue FOR INSERT TO authenticated
  WITH CHECK (
    user_id = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(
      workspace_id, ARRAY['owner','admin','editor']
    ))
  );

CREATE POLICY shorts_topic_queue_member_delete
  ON public.shorts_topic_queue FOR DELETE TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(
      workspace_id, ARRAY['owner','admin','editor']
    ))
  );
```

## Lifecycle and security properties

- `user_id` and `workspace_id` are both required in every REST filter; the RLS policy independently enforces the same user/workspace boundary.
- A user can see and delete only their own saved topics, even when multiple users share one workspace.
- Deleting a user cascades only that user's saved topics. Deleting a workspace cascades that workspace's queue rows. Leaving a shared workspace does not delete another member's rows.
- A normalized unique key prevents duplicate topics under whitespace/case differences.
- Only HTTPS source links are stored. No update permission is granted.
- No worker claim/status/lease columns exist; the table is not a job queue and cannot be consumed by render/upload workers.
- No `service_role` key is needed by the browser API; requests use the verified end-user JWT and publishable key.

## Application wiring

- `supabase_rest.py` allowlists the table and exposes a filtered DELETE method.
- `api_server.py` provides list/add/delete endpoints with explicit workspace and user filters.
- `signup.html` uses server storage when the table exists and preserves browser-local items as a temporary fallback while the migration is pending.
- API tests verify tenant/user scoping, HTTPS validation, duplicate conflicts, and the migration-pending fallback.

## Activation gate

Do not apply this schema to the live `ai_studio` project without separate explicit authorization. Before enabling server mode in a deployed environment, run the migration locally, inspect the diff, run Supabase security/performance advisors, and verify two users in the same workspace cannot read/delete one another's rows. Keep the existing account-deletion and shared-workspace invariants intact.
