# NEXUS Discovery and Analytics API Contract

## Discovery radar

### GET /api/radar/{period}

Returns cached discovery records only. A read request never triggers external feed scans.

- `period`: `daily` or `weekly`
- `items[]`: source-attributed topic records
  - `region`, `source_name`, `source_url`
  - `source_rank`: position within that source's own feed
  - `source_score` and `source_score_label`: present only when the source provides a native score (currently Hacker News points)
  - `est_views`, `avg_cat_views`, `growth_pct`, `viral_score`: null until a comparable verified source exists
  - `source_status`, `source_error`, `source_is_stale`: status from the latest scan for the requested period
- `scan`: last scan timestamp, status, item count, and per-source result summary
- `data_status`: `not_scanned`, `fresh`, `partial`, or `stale`
- `global_ranking_available`: false until cross-source metrics are comparable

### POST /api/radar/scan/{period}

Explicitly starts a scan and returns the actual fetched item count and source-level scan result. Partial source failures are reported as `partial`; a total failure is reported as `failed`. The last successful rows for failed feeds are retained and marked stale rather than silently deleted.

### Automatic production selection

Automatic production selects fresh, successful source rows using source-local order and a balanced region rotation. It does not combine Hacker News points with RSS order or fabricate a global viral ranking.

## Analytics

### GET /api/analytics/summary

Returns local production and publishing facts:

- Job totals and counts by stage/channel
- Confirmed private uploads, uploads in progress, privacy-unverified uploads
- Daily/weekly discovery scan state and source health

YouTube subscriber, view, engagement, and revenue fields remain null with `platform_metrics.status=not_connected` until authorized read-only YouTube Analytics credentials and provider data are available. Upload credentials alone are not treated as analytics access.

## Operations

### GET /api/ops/metrics

Returns queue/scheduler/pipeline counts, source health, last daily/weekly radar scan, oldest pending queue timestamp, and recent audit-event activity.

No endpoint estimates views, growth, revenue, or cross-source popularity without provider evidence.
