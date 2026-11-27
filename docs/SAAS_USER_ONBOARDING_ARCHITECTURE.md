# NEXUS STUDIO PRO — SaaS User Registration & YouTube Account Linking

Status: Phase A identity and signup/login UI, Phase B workspace-scoped Shorts schema/APIs, and Phase C Google Web OAuth server flow foundations are implemented. Live Google consent, tenant-bound worker execution, and end-to-end SaaS verification remain in progress.
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
