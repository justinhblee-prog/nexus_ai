# NEXUS STUDIO PRO — SaaS User Registration & YouTube Account Linking

Status: Phase A identity and signup/login UI, Phase B workspace-scoped Shorts schema/APIs, Phase C Google Web OAuth foundations, Phase D opt-in tenant-aware rendering/review, and Phase E private-only approved YouTube upload foundations are implemented. Live Google consent, live worker activation, and end-to-end SaaS verification remain in progress.
Target: `feat/nexus-user-onboarding-web-oauth-20261127`, based on the current full-stack integration branch.

## Phase A implementation delivered

- Selected existing Supabase service project: `ai_studio` (Seoul region), Free Plan.
- Added `profiles` with self-only SELECT/UPDATE RLS.
- Added `workspace_name` to the existing `workspaces` table; did not recreate existing workspace or content tables.
- Added a private, non-exposed Auth trigger that creates a profile and a personal workspace when Supabase Auth inserts a new user.
- Reuses the existing workspace-owner membership trigger to grant the new user the owner role.
- Replaced recursive workspace-membership policy lookups with a private owner-check helper that binds authorization to `auth.uid()`.
- Added server-side Supabase JWT verification using the project JWKS, issuer, audience, expiry, subject UUID, and authenticated-role checks; legacy HS256 tokens are verified by calling Supabase Auth's `/auth/v1/user` endpoint with the publishable key.
- Added public auth configuration that exposes only the project URL and publishable key, explicitly rejecting service-role keys (including legacy JWT-form keys).
- Added a hosted-auth safety gate: hosted mode blocks legacy single-operator SQLite API and media routes until tenant-scoped equivalents are implemented; only verified hosted-session and public auth-config routes remain available.
- Added a responsive `/signup` page with email registration, login, verification redirect, password recovery/update, session refresh, logout, and personal workspace display after backend identity verification.
- Added a dashboard entry point to the account page.
- Added regression tests for token validation, service-role key rejection, signup UI contract, and fail-closed route isolation.
- No service-role key, Google client secret, or token is stored in browser-visible data.
- No additional Supabase project, paid add-on, or paid resource is used.

## Phase B implementation delivered

- Added workspace-scoped `youtube_connections`, `shorts_channels`, `shorts_jobs`, `shorts_job_events`, `shorts_analytics_snapshots`, and `shorts_assets` tables.
- Added private `youtube_oauth_credentials` and `youtube_oauth_states` tables with RLS enabled, no client grants, and no client policies (intentional deny-by-default).
- Added an AES-256-GCM token vault with authenticated associated data, ciphertext-only storage, strict 32-byte key validation, and versioned key rotation. Encryption keys are server-only environment values and are never committed.
- Added server-only Supabase admin access and RPCs for one-time OAuth state consumption and private credential read/write/delete. RPC execution is explicitly denied to `anon` and `authenticated` and granted only to `service_role`.
- Added Google Web OAuth helpers for PKCE, offline consent, exact callback URI, Google account identity lookup, all-channel discovery from YouTube API, and provider token revocation.
- Stored one encrypted refresh token per Google account/workspace connection and linked every discovered channel to that connection. Disconnect revokes the Google grant only when no other active workspace connection uses the same Google account.
- Added API routes for owner/admin YouTube connect initiation, public one-time callback, channel listing, and disconnect/revoke. The callback binds Google identity to the workspace from the consumed server-side state and encrypts refresh tokens before persistence.
- Added a private worker lease table with `SKIP LOCKED` job claims, heartbeat renewal, attempt limits, and fencing tokens. Worker RPCs are service-role-only.
- Added a private `nexus-shorts` Storage bucket (100 MB per object) with workspace-folder RLS policies. Rendered assets are private and previews use 5-minute signed URLs after user-JWT/RLS checks.
- Added an opt-in Docker `hosted-render-worker` profile. It uses the existing Shorts renderer with an empty OpenAI key (free fallback only), runs ffprobe QA, stores tenant-prefixed MP4s, and stops at `review_pending` for human approval.
- Verified the live database worker lifecycle in a rolled-back transaction: job claim, lease heartbeat, render completion, private media path enforcement, and owner approval moved the job to `approved`. Temporary user/job/lease rows were confirmed absent afterward.
- The hosted worker remains disabled by default and was not started; no real media was uploaded to Storage and no YouTube upload was performed.
- Added hosted account UI controls for channel connect/disconnect, Shorts job creation, rendered preview, and owner/admin final approval. Approval transitions the job to `approved`.
- Added an opt-in private YouTube upload worker that only claims approved jobs, refreshes the encrypted account token, downloads the private render, verifies that the Google account exposes exactly the selected YouTube channel, and uploads with `privacyStatus=private`.
- Uploads are capped at three per Pacific calendar day and two attempts per job. The worker records the provider video ID before finalizing to reduce duplicate uploads after retries. Approval cannot be revoked once upload starts.
- Jobs finish in `published` stage with `privacy_status=private`; this means uploaded to YouTube privately, not publicly published. Public visibility must be changed manually in YouTube Studio. Accounts exposing multiple channels fail closed rather than risk uploading to the wrong channel.
- Added role-aware RLS for owner/admin/editor/viewer access, restricted column-level mutation grants, and a trigger that permits approval-status changes only by workspace owners/admins.
- Enforced private-only upload privacy and disallowed approved/uploading/published job stages until approval is recorded; published jobs also require provider video ID and upload timestamp.
- Added a private workspace-role helper that derives identity from `auth.uid()`, not browser-supplied user IDs.
- Verified two-user workspace isolation, editor job edits, owner approval, and private-by-default constraints inside rolled-back transactions.

## Remaining Phase A work

- Configure Supabase Auth site URL and redirect allowlist for the actual hosted domain.
- Configure the actual Supabase Auth Site URL and redirect allowlist for the hosted domain; verify signup/email confirmation/login/recovery against a real test mailbox.
- Implement secure account deletion and credential revocation.
- Bind existing render workers, media storage, queue processing, analytics ingestion, and upload approvals to the verified workspace context; the new schema/API does not yet migrate the local SQLite pipeline.
- Connect hosted workspace jobs to the production render/upload pipeline only after tenant-safe worker execution is implemented.
- Verify cross-user access denial with two isolated test identities in the same project.

## Next phases

### Phase B — Web OAuth and channel management
Use a separate Google OAuth Web Application client. Implement user-bound, one-time OAuth state, callback validation, channel identity discovery, encrypted refresh-token persistence, reconnect, disconnect, and revoke handling. The existing Desktop OAuth client remains local-development-only.

### Phase C — Tenant-safe production pipeline
Add workspace ownership to queue/jobs/channels/analytics/audit/media. Scope API queries, worker jobs, upload approvals, media previews, and metrics by workspace. Preserve human approval and private-by-default uploads.

### Phase D — Operations and compliance
Add trusted admin roles, retention, account export/deletion, credential revocation, privacy policy, terms, support contact, audit, and incident procedures.

## Security invariants

- Fail closed on missing/invalid user identity or tenant context.
- Never trust user IDs supplied by the browser for authorization.
- Never expose Supabase service-role/secret keys or Google OAuth client secrets to clients.
- Keep YouTube refresh tokens encrypted at rest and redact credentials from logs.
- Keep YouTube uploads private and require explicit human approval.
- Do not claim public SaaS readiness until Phases A–C and two-user end-to-end tests pass.


## Hosted activation checklist (not enabled yet)

1. Choose the final HTTPS application origin and API origin. The app origin must be configured as `NEXUS_HOSTED_APP_URL`; the exact callback is `NEXUS_GOOGLE_OAUTH_REDIRECT_URI=https://<API_ORIGIN>/api/hosted/youtube/callback`.
2. In Google Cloud Console, create a separate **Web application** OAuth client (do not reuse the local Desktop client). Add the app origin as an authorized JavaScript origin and the exact callback above as an authorized redirect URI. Keep the client secret server-side.
3. In Supabase Auth URL Configuration, set the final app origin as Site URL and allow the exact `https://<APP_ORIGIN>/signup` redirect. Enable the Email provider and email confirmation.
4. Configure server-only environment values: `NEXUS_SUPABASE_SERVICE_ROLE_KEY` (legacy service_role JWT), `NEXUS_TOKEN_ENCRYPTION_KEY` or versioned keyring, `NEXUS_GOOGLE_OAUTH_CLIENT_ID`, `NEXUS_GOOGLE_OAUTH_CLIENT_SECRET`, `NEXUS_GOOGLE_OAUTH_REDIRECT_URI`, and `NEXUS_HOSTED_APP_URL`. Never paste these values into chat or commit them.
5. Set `NEXUS_CORS_ALLOWED_ORIGINS` only if the browser app and API are on different origins.
6. Keep `NEXUS_HOSTED_AUTH_ENABLED=false` until tenant-scoped render workers, queue, media, analytics, and upload execution are implemented and verified. Enabling it now intentionally blocks the legacy single-operator API/media routes; the account/OAuth endpoints alone do not make the full Shorts pipeline SaaS-ready.
