-- Shared public trend snapshots for hosted workspaces.
-- Only the opt-in server worker may write; authenticated workspace members may read.
CREATE TABLE IF NOT EXISTS public.public_trend_signals (
  signal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  period_type text NOT NULL CHECK (period_type IN ('daily', 'weekly')),
  region text NOT NULL CHECK (char_length(region) BETWEEN 2 AND 12),
  rank_no integer NOT NULL CHECK (rank_no > 0),
  topic text NOT NULL CHECK (char_length(btrim(topic)) BETWEEN 1 AND 500),
  source_name text NOT NULL CHECK (char_length(btrim(source_name)) BETWEEN 1 AND 120),
  source_url text CHECK (source_url IS NULL OR source_url ~ '^https://'),
  source_score bigint,
  source_score_label text,
  growth_pct integer,
  viral_score integer,
  ai_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (period_type, region, source_name, topic)
);

CREATE INDEX IF NOT EXISTS idx_public_trend_signals_feed
  ON public.public_trend_signals (period_type, rank_no, region, source_name);

CREATE TABLE IF NOT EXISTS public.public_trend_scans (
  period_type text PRIMARY KEY CHECK (period_type IN ('daily', 'weekly')),
  status text NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
  started_at timestamptz,
  completed_at timestamptz,
  item_count integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
  successful_sources integer NOT NULL DEFAULT 0 CHECK (successful_sources >= 0),
  failed_sources integer NOT NULL DEFAULT 0 CHECK (failed_sources >= 0),
  source_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.public_trend_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.public_trend_scans ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.public_trend_signals FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.public_trend_scans FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.public_trend_signals TO authenticated;
GRANT SELECT ON TABLE public.public_trend_scans TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.public_trend_signals TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.public_trend_scans TO service_role;

CREATE POLICY public_trend_signals_authenticated_read
  ON public.public_trend_signals FOR SELECT TO authenticated
  USING (true);

CREATE POLICY public_trend_scans_authenticated_read
  ON public.public_trend_scans FOR SELECT TO authenticated
  USING (true);
