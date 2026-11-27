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
      workspace_id, ARRAY['owner','admin','editor','viewer']
    ))
  );

CREATE POLICY shorts_topic_queue_member_delete
  ON public.shorts_topic_queue FOR DELETE TO authenticated
  USING (
    user_id = (SELECT auth.uid())
    AND (SELECT private.has_workspace_role(
      workspace_id, ARRAY['owner','admin','editor','viewer']
    ))
  );
