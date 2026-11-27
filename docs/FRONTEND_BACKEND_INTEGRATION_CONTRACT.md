# NEXUS Frontend / Backend Integration Contract

Status: working contract for parallel implementation
Branch: `feat/nexus-workspace-ui-four-layouts`
Updated: 2026-11-27

## Product invariants

- Seven workspaces: Dashboard, AI Content Studio, Discovery, Review, Publishing, Analytics, Operations.
- The four dashboard presentation modes (Intelligence, Creator, Global Analytics, Executive Intelligence) are views over the same data and capabilities. They must not fork business logic or fabricate metrics.
- Appearance settings (palette, accent, density, typography/card treatment) are independent from the selected presentation mode.
- Human approval is mandatory before upload. Upload defaults to private. No automatic public transition.
- Missing measurements remain unavailable/null; never invent views, engagement, growth, or revenue.

## Existing frontend API calls observed in `index.html`

| Endpoint | Purpose | Current consumer |
|---|---|---|
| `GET /api/session/status` | Session/configuration state | Login gate |
| `POST /api/session/login` | Create session | Login gate |
| `POST /api/session/logout` | End session | Logout |
| `GET /api/radar/{daily|weekly}` | Discovery radar items | Discovery |
| `POST /api/create` | Enqueue a topic for a channel | Discovery / Studio |
| `GET /api/overview` | Channels and jobs overview | Dashboard / Studio |
| `GET /api/ops/metrics` | Queue, pipeline and source metrics | Operations |
| `GET /api/events?limit=N` | Recent operational events | Operations |

Existing response fields are consumed by the UI; avoid breaking them without a versioned migration.

## Required normalized data shapes

### Job
- `id`: stable identifier
- `channel_name`: channel label
- `topic`: topic/title
- `script`: nullable script text
- `video_path`: nullable generated asset path
- `status` and/or `stage`: explicit lifecycle state
- `created_at`, `updated_at`: timestamps
- `error`: nullable safe error summary

### Discovery item
- `id`, `topic`, `region`, `source_name`, `source_url`
- `matched_channel`, `rank_no`, `is_global_top10`
- Any quantitative field must be source-backed; absent data must be null.

### Overview
- `channels[]`
- `jobs[]`
- Include queue/pipeline state only when sourced from persisted backend state.

## Workspace responsibilities

- Dashboard: operational KPIs, channel performance, regional content mix, production queue.
- Discovery: source-backed trends, region filters, enqueue action.
- AI Content Studio: job creation, scripts/assets, progress and QA state.
- Review: QA result, preview, edit/re-review, explicit approve/reject.
- Publishing: approved jobs, destination/channel, publish result, privacy state.
- Analytics: source-backed performance and date/channel/region dimensions.
- Operations: queue health, retries/quarantine, source health, audit/event log.

## Parallel ownership / file coordination

- BACKEND-01: production queue, topic-to-video pipeline, job lifecycle and progress API.
- BACKEND-02: QA, review transitions, human approval, upload safety and audit trail.
- BACKEND-03: discovery/analytics/operations read models and source provenance.
- Frontend: `index.html`, presentation modes, navigation, appearance settings and API consumption.

All backend tasks must coordinate changes to `api_server.py` through this contract and avoid simultaneous conflicting edits. Backend task tickets are #2, #3, #4.

## Acceptance checks

1. A discovery item can be enqueued, generated, QA-checked, reviewed, approved, uploaded privately, and later measured where platform data exists.
2. No upload occurs before explicit human approval.
3. A retry or duplicate request cannot create duplicate active work or duplicate uploads.
4. UI shows loading, empty, partial-data, error, and stale-data states.
5. Four presentation modes show the same underlying facts; only hierarchy/layout changes.
6. Appearance customization does not change data, permissions, or workflow.
7. API and regression tests pass; no production deployment is part of this PR.
