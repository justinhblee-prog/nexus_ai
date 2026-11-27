# NEXUS STUDIO PRO — SaaS User Registration & YouTube Account Linking

Status: architecture baseline; implementation not yet production-ready.
Target: `feat/nexus-user-onboarding-web-oauth-20261127`, based on the current full-stack integration branch.

## 1. Product requirement

The existing Desktop OAuth client and local `tokens/client_secret.json` are developer-only credentials. They are not a registration mechanism and must never be distributed to end users.

A public NEXUS account must be able to:
1. Register and verify an email address (and optionally sign in with Google).
2. Sign in/out and manage sessions.
3. Create an isolated workspace.
4. Connect one or more YouTube channels using a separate Google OAuth consent flow.
5. See per-channel upload and Analytics permissions, reconnect, and disconnect.
6. Delete the account and request deletion of associated profile, channel-token, and workspace data.

NEXUS account authentication and YouTube channel authorization are separate identities and separate consent events.

## 2. Recommended hosted architecture

- Identity: Supabase Auth for email/password + email verification, password reset, and optional Google sign-in.
- Application data: Supabase Postgres for hosted multi-user workspace, membership, channel connections, and audit records.
- Authorization: Row Level Security on every exposed tenant table. Every tenant-owned row has a non-null `owner_user_id` referencing `auth.users(id)`; policies compare it with `auth.uid()`. Never authorize using user-editable user metadata.
- YouTube linking: a distinct server-side Google OAuth Web Application client, not the current Desktop client. Require a one-time, expiring, user-bound OAuth state (and PKCE where supported); validate the callback and bind the resulting Google channel identity to the authenticated NEXUS user.
- Secrets: Google client secret and token-encryption key stay in server-side secret storage. Never expose service-role/secret keys or Google client secrets to the browser.
- YouTube refresh tokens: encrypt at rest with authenticated encryption; store key version and ciphertext only. Never log authorization codes, access tokens, refresh tokens, client secrets, or full callback URLs.
- API: verify Supabase access tokens server-side; derive user identity from verified claims. Never accept `owner_user_id` from a request body as authority.
- Existing local SQLite runtime: retain as developer/local single-operator mode. Do not silently reinterpret its global jobs/channels database as multi-tenant data.

## 3. User and channel lifecycle

### Registration
1. User submits email/password or chooses Google sign-in.
2. Supabase Auth creates the identity and sends verification.
3. Verified identity receives a workspace/profile row.
4. The user enters the NEXUS workspace only after a valid authenticated session.

### YouTube channel connection
1. Authenticated user clicks “Connect YouTube channel”.
2. Backend creates a short-lived, single-use state bound to the current user and requested scopes.
3. Browser is redirected to Google OAuth Web Application consent.
4. Callback validates state, exchanges the code server-side, fetches the authenticated YouTube channel identity, and stores an encrypted refresh token linked to that user and channel.
5. UI shows granted scopes and separate upload/Analytics readiness.
6. Reconnect updates the existing user/channel connection; disconnect revokes tokens where supported and deletes stored credentials.

Google login is not equivalent to YouTube upload permission. The user must explicitly grant the YouTube scopes required by the feature.

## 4. Initial data model

- `profiles`: `id = auth.users.id`, display name, created/updated timestamps.
- `workspaces`: id, owner_user_id, name, timestamps.
- `workspace_members`: workspace_id, user_id, role, unique(workspace_id,user_id).
- `youtube_connections`: id, owner_user_id, workspace_id, Google subject/channel id, channel title, encrypted refresh-token payload, encryption key version, granted scopes, status, connected/updated timestamps. Unique(owner_user_id, channel_id).
- `oauth_transactions`: opaque state hash, user_id, expiry, consumed_at, PKCE verifier ciphertext if used. Never persist raw state.
- `audit_events`: workspace_id, actor_user_id, event type, resource type/id, timestamp, redacted metadata.

All exposed tables require RLS. Policies must enforce ownership/membership for SELECT, INSERT, UPDATE, and DELETE. UPDATE policies require both USING and WITH CHECK. Add indexes for owner/workspace lookups and foreign keys with deliberate deletion behavior. Never store Google tokens in browser storage or user metadata.

## 5. Multi-tenant migration boundary

Before public onboarding:
- Inventory every SQLite table and every API/Streamlit route that reads or mutates channels, jobs, queue entries, analytics, generated media, and audit events.
- Add an explicit tenant/workspace key to all tenant-owned records and enforce it in every query and media-serving path.
- Ensure background workers carry an explicit workspace/owner context; never infer tenant identity from a global channel name.
- Isolate media paths by workspace and authorize every download/preview.
- Keep local single-user behavior behind an explicit local mode; hosted mode must fail closed if identity or tenant context is absent.
- Migrate existing local data only through an explicit owner-assignment process; do not guess an owner.

## 6. Delivery phases and acceptance criteria

### Phase A — Identity foundation
- Configure the selected hosted Supabase project and Auth redirect/site URLs.
- Implement signup, email verification, login, logout, password reset, session refresh, and account deletion.
- Add profiles/workspaces/memberships migrations with RLS and automated cross-user denial tests.
- Verify unauthenticated requests fail closed and user A cannot read/update/delete user B's data.

### Phase B — Web OAuth and channel management
- Create a Google OAuth Web Application client with HTTPS redirect URI(s).
- Implement user-bound one-time OAuth state, callback validation, channel identity discovery, scope inspection, encrypted refresh-token persistence, reconnect, disconnect, and revoke handling.
- Add tests for state mismatch/replay/expiry, callback errors, missing scopes, token encryption, and cross-user channel isolation.
- Verify channel A tokens cannot be retrieved or used by user B.

### Phase C — Tenant-safe production pipeline
- Add workspace ownership to queue/jobs/channels/analytics/audit/media.
- Scope all API queries, worker jobs, upload approvals, media previews, and metrics by workspace.
- Preserve human approval before upload and private-by-default uploads.
- Run end-to-end signup → connect channel → create job → review → private upload → analytics tests using two independent users.

### Phase D — Operations and compliance
- Add admin roles using trusted server-managed claims or membership records, never user-editable metadata.
- Add retention, account export/deletion, token revocation, privacy policy, terms, support contact, and incident/audit procedures.
- Complete Google OAuth consent-screen verification and YouTube API policy review before public distribution.

## 7. Current blockers / decisions

- Existing Supabase projects visible to the connected account are named `ai_studio` and `ai_studio_test`, and both currently report INACTIVE. Neither is assumed to be the NEXUS production project.
- Do not create, activate, restore, or incur project costs without explicit project selection and cost approval.
- The current Desktop OAuth client remains for local development only. It cannot serve public web callbacks.
- No public registration or multi-tenant isolation is claimed until Phases A–C are implemented and verified.
- No merge to `main`, deployment, or public publishing is part of this branch.

## 8. Security invariants

- Fail closed on missing/invalid user identity or tenant context.
- Never trust user IDs supplied by the browser for authorization.
- Never expose Supabase service-role/secret keys or Google OAuth client secrets to clients.
- Encrypt YouTube refresh tokens at rest; redact all credentials from logs.
- Use least-privilege YouTube scopes and request them only when the user connects YouTube.
- Keep YouTube uploads private and require the existing explicit human approval.
- Account deletion must revoke/delete connected credentials and apply the documented data-retention policy.
