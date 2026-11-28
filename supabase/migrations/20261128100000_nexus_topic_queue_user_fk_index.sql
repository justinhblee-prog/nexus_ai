-- The existing workspace/user composite index starts with workspace_id and
-- therefore cannot serve lookups or FK checks by user_id alone.
CREATE INDEX IF NOT EXISTS idx_shorts_topic_queue_user_id
  ON public.shorts_topic_queue (user_id);
