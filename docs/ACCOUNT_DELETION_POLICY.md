# NEXUS account deletion and workspace ownership policy

## Current implementation status

Account deletion is a required SaaS feature. The Draft PR now contains a gated request endpoint, durable queue, a resumable worker, Storage/OAuth cleanup, Auth deletion, and post-cleanup verification. The API and worker are disabled by default. No production migration has been applied and no user data has been deleted.

The API accepts a deletion request only when the dedicated worker has written a heartbeat within the last 90 seconds, in addition to the following conditions:
- The caller's verified JWT contains a signed `amr` password-authentication timestamp no older than 10 minutes; token refresh alone does not satisfy this check.
- The caller submits the exact confirmation phrase `DELETE MY ACCOUNT`.
- The read-only preflight has no ownership, active-worker, shared-Storage, or unclassified-Storage blockers.
- Both `NEXUS_ACCOUNT_DELETION_ENABLED` and `NEXUS_ACCOUNT_DELETION_WORKER_ENABLED` are explicitly enabled after the migration and deployment configuration are reviewed.

The queue RPC atomically creates a non-FK tombstone and a durable request. The worker cannot claim a request until global refresh-session revocation has been confirmed and persisted. The render and private-upload claim RPCs also exclude jobs in workspaces still owned by a tombstoned account, closing the race between preflight and a new job lease. If session revocation fails, the user may retry the same request endpoint; the middleware permits only that exact POST path for an already-tombstoned account.

## Workspace rules

1. A user may leave a workspace where they are a member without deleting the workspace.
2. An owner must transfer ownership to an existing admin before deleting their account if other members remain.
3. Ownership transfer is atomic: the selected admin becomes `owner`, and the previous owner becomes `admin`.
4. The owner may promote an existing member to admin before transfer. The transfer RPC derives the acting user from `auth.uid()`; caller-supplied identity is never trusted.
5. A sole-member workspace may be removed during account deletion. Shared workspaces and their content must never be cascade-deleted because one member leaves.
6. The worker re-reads memberships and ownership using the service role immediately before destructive operations. It does not trust the preflight snapshot as authorization.

## Shared workspace records

Shorts jobs, channels, assets, connections, review events, and legacy workspace assets may outlive the person who created them. The migration makes author/reviewer fields nullable and uses `ON DELETE SET NULL` for the Shorts domain. For legacy shared workspace records, the worker anonymizes `assets.owner_id`, `characters.owner_id`, `generation_jobs.owner_id`, and `character_bundle_imports.user_id` rather than deleting the shared content.

The worker removes only the departing user's membership row from shared workspaces. It preserves their other members, workspace ownership, channels, jobs, media, and OAuth connections.

## Resumable deletion workflow

1. Require fresh password reauthentication (verified through the signed AMR timestamp) and explicit confirmation.
2. Run the read-only preflight. Reject requests with ownership-transfer, active-worker, shared-storage, or unclassified-storage blockers.
3. In one database transaction, create the durable deletion request and persistent tombstone. The tombstone blocks ordinary hosted API requests even if an access JWT has not expired.
4. Revoke all refresh sessions using the caller's verified bearer token. Persist `sessions_revoked=true`; the worker's claim RPC filters out every request without this flag.
5. Claim the job with `FOR UPDATE SKIP LOCKED`, a unique worker lease, and a bounded lease expiry. Heartbeat long-running jobs. Expired leases can be reclaimed after a worker crash.
6. Re-read the user's memberships and owned workspaces. If the user still owns a shared workspace, mark the job blocked and retry daily so an ownership transfer can unblock it. Never delete a shared workspace.
7. Wait while render or private-upload leases are active. Retry later instead of racing a worker.
8. Inventory YouTube connections only in sole-member workspaces scheduled for deletion. If an active provider account is also connected in another workspace, preserve the provider grant. Otherwise persist a `revocation_started` checkpoint keyed by a one-way SHA-256 fingerprint of the provider account ID, decrypt a refresh token in server memory, and revoke the Google grant. Persist `revoked` before deleting credentials; `preserved` and `not_required` are terminal checkpoints too. If the worker crashes after Google revokes but before the checkpoint is written, retry the same token. Google documents HTTP 400 as an error response and does not guarantee that it means an already-revoked token; therefore any response other than HTTP 200 remains unconfirmed, keeps the encrypted credential intact, and retries without marking the grant revoked or deleting the account. A retry after the `revoked` checkpoint never needs the deleted credential or repeats the provider call. Delete credentials only for connections in the deleted workspaces. Never log or persist plaintext tokens or raw provider account IDs in the checkpoint journal.
9. Inventory Storage objects owned by the user, all objects under sole-member workspace prefixes, and personal gallery image/thumbnail keys. Block deletion if an object belongs to a shared workspace, has an ambiguous bucket, uses an unsupported bucket, or cannot be mapped safely. Delete each allowed object through the exact bucket's Storage API; never delete `storage.objects` rows with SQL.
10. Delete workspace-scoped legacy generation jobs whose FK uses `ON DELETE SET NULL`, anonymize authorship on retained shared legacy records, remove personal gallery metadata and private idempotency/OAuth-state rows, and then delete sole-member workspaces. Workspace cascade removes their channels, Shorts jobs, assets, connections, worker leases, and encrypted OAuth credentials.
11. Remove the departing user's membership from every remaining shared workspace and remove their profile.
12. Verify that no user-owned Storage objects, private idempotency/OAuth-state rows, workspace ownership, memberships, or legacy author references remain. Only then call the server-only Supabase Auth Admin delete endpoint.
13. Verify again after Auth deletion. Mark the queue request `completed` only after all checks return zero. If any operation fails, keep the tombstone and durable request and retry from the idempotent cleanup steps.

The queue stores only a minimal preflight snapshot and sanitized error codes. It never stores an access token, refresh token, password, or OAuth secret. Completed tombstones remain without a foreign key to `auth.users`, so stale JWTs remain blocked.

## Explicit safety constraints

- Never cascade-delete a shared workspace.
- Never delete another member's content or YouTube connection.
- Never expose service-role credentials or OAuth tokens to the browser.
- Never treat an Auth Admin HTTP success as proof that Storage and provider credentials were cleaned.
- Never mark a request complete before post-Auth verification.
- The worker is opt-in and disabled by default. Its heartbeat is required before the API exposes the final deletion confirmation, preventing irreversible requests from being accepted while the cleanup service is offline. Do not enable it until the reviewed migration is applied and free-tier service configuration is verified.
- No paid APIs or infrastructure are required by this workflow.

## Storage and Auth adapter safeguards

- Storage inventory is restricted to a service-role-only RPC and paginated in batches of at most 1,000 rows. It includes account-owned objects across buckets, every object under sole-member workspace prefixes, and personal gallery image/thumbnail keys.
- Active render/upload lease inventory is restricted to a service-role-only RPC.
- OAuth connection inventory returns metadata only, never ciphertext or token material. Provider grant reuse is checked outside all workspaces scheduled for deletion.
- Storage deletion uses the Storage API with an exact bucket and object path. The adapter rejects unknown buckets, absolute paths, empty path segments, dot segments, and backslashes. Already-missing objects are treated idempotently.
- Auth Admin deletion is server-only and is not exposed directly to the browser.
- Tombstones and queue rows have no FK to `auth.users`; they survive final Auth deletion.
- Global session revocation uses the verified user's bearer token, not the service-role token as the user identity.
- The current live project inspection found zero rows in legacy assets, characters, generation jobs, character bundle imports, gallery images, and Storage objects at the time of inspection. This is only an observation, not a permanent assumption; every deletion performs fresh runtime inventory.
