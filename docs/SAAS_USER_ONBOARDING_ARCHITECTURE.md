# NEXUS STUDIO PRO — SaaS User Registration & YouTube Account Linking

Status: Phase A database identity bootstrap, hosted JWT verification, and responsive signup/login UI implemented; hosted Auth redirect configuration, tenant-scoped application APIs, and end-to-end signup verification remain in progress.
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

## Remaining Phase A work

- Configure Supabase Auth site URL and redirect allowlist for the actual hosted domain.
- Configure the actual Supabase Auth Site URL and redirect allowlist for the hosted domain; verify signup/email confirmation/login/recovery against a real test mailbox.
- Implement secure account deletion and credential revocation.
- Add tenant-scoped application endpoints and bind every query/worker/media operation to the verified workspace membership.
- Connect hosted signup/session to the production workspace experience only after tenant-safe APIs are ready.
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
