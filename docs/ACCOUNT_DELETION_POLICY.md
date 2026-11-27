# NEXUS account deletion and workspace ownership policy

## Current status

Account deletion is a required SaaS capability, but the destructive Auth deletion endpoint is intentionally not exposed yet. The account-lifecycle work in this PR establishes the safe ownership-transfer and audit-preservation prerequisites, plus a read-only deletion preflight that inventories account-owned Storage objects through a service-only database RPC. Server-only helpers now cover exact Storage API object deletion, global refresh-session revocation, and the Supabase Auth Admin deletion endpoint. They are not yet wired into a destructive workflow. No production migration or user deletion has been executed.

## Workspace rules

1. A user may leave a workspace where they are a member without deleting that workspace.
2. A workspace owner must transfer ownership to an existing admin before deleting their account when other members remain.
3. The transfer operation changes the workspace owner and membership roles atomically: the selected admin becomes `owner`, and the previous owner becomes `admin`.
4. The owner can list workspace members and promote a member to admin before transfer. The transfer function derives the acting user from `auth.uid()`; caller-supplied identity is never trusted.
5. `GET /api/hosted/account/deletion/preflight` reports owned workspaces, whether an admin is available, and the transfer blockers. It does not start deletion and explicitly reports that deletion is not enabled.
5. A sole-member workspace may be removed as part of the account deletion workflow. A shared workspace must never be cascade-deleted merely because its former owner account is removed.

## Shared workspace records

Shorts jobs, channels, assets, connections, and review events may outlive the person who created them. Their author/reviewer foreign keys are nullable and use `ON DELETE SET NULL`, preserving the workspace content and audit event while removing the deleted identity reference.

## Required deletion saga (not yet implemented)

The eventual server-only deletion workflow must be idempotent and resumable:

1. Require a fresh reauthentication step and an explicit account-deletion confirmation.
2. Block deletion while the user owns any workspace with other members. Return the workspace IDs and require ownership transfer first.
3. Mark the account as deletion-pending and prevent new workspace writes/jobs for that user.
4. Stop new work for workspaces that will be deleted and wait until both render and private-upload leases have expired. The deletion preflight now inventories active hosted worker leases through a service-only RPC and reports the latest lease expiry; it never deletes a workspace while a lease is active.
5. Inventory YouTube connections only in sole-member workspaces that will be deleted. For each, decrypt the refresh token in server memory, revoke the Google grant only if no other active NEXUS workspace connection uses the same provider account, then delete the encrypted credential. Preserve connections and credentials in shared workspaces after ownership transfer; they are workspace resources, not personal tokens. Record revocation outcomes without storing token material. The preflight now reports how many credentials need cleanup and how many distinct provider grants must be preserved for active connections outside all workspaces scheduled for deletion. Duplicate connections inside the deletion set are counted as one provider grant.
6. Enumerate Storage objects owned by the user across all NEXUS buckets through the service-only inventory RPC. If a user-owned object is inside a shared workspace, block deletion until the file is safely re-uploaded or ownership is otherwise transferred; never remove a shared team's only copy. For deletable objects, call the Storage API for each exact bucket/path. Do not delete Storage metadata rows directly.
7. Delete the user's sole-member workspaces and their workspace-scoped records. Preserve all shared workspaces and their content.
8. Remove any remaining user-owned personal assets according to the product retention policy.
9. Revoke sessions and delete the Auth user through the Supabase Auth Admin API.
10. Persist a non-FK account tombstone before revoking sessions. The hosted API middleware checks the tombstone with the caller's verified JWT and blocks further requests, including otherwise unexpired access JWTs. Revoke the user's global Supabase refresh sessions using their verified access token. Then delete the Auth user through the server-only Auth Admin endpoint.
11. Verify no user-owned Storage objects, OAuth credentials, workspace ownership, or user foreign-key references remain. Mark the deletion request complete only after verification.

If any external cleanup fails, retain a retryable deletion-pending record and do not report completion. Do not partially delete the Auth identity while required cleanup is still outstanding.

## Explicit safety constraints

- Never cascade-delete a shared workspace.
- Never delete another member's content or YouTube connection.
- Never expose service-role credentials or OAuth tokens to the browser.
- Never treat an HTTP success from the Auth Admin API as proof that Storage and provider credentials were cleaned.
- Account deletion is not complete until the verification step succeeds.


## Storage and Auth adapter safeguards

- Storage inventory is restricted to a service-role-only RPC and paginated in batches of at most 1,000 rows.
- Active render/upload lease inventory is restricted to a separate service-role-only RPC; it covers the hosted Shorts render and upload lease tables.
- OAuth connection inventory returns only connection metadata, never ciphertext or token material. It checks other active connections before deciding whether a Google grant can be revoked.
- Storage object deletion uses the Storage API with an exact bucket and object path. The adapter rejects unknown buckets, absolute paths, empty path segments, dot segments, and backslashes.
- The Auth Admin deletion helper is server-only and is not exposed as an HTTP route.
- A tombstone table has no foreign key to `auth.users`, so it survives final Auth deletion. Authenticated users can only query their own tombstone state; only service-role code can create tombstones.
- Global session revocation uses the verified user's bearer token, not the service-role token as the user identity.
- The account deletion preflight fails closed if it cannot verify Storage ownership.
- The currently observed NEXUS buckets are private: `acs-assets`, `acs-gallery`, `acs-outputs`, and `nexus-shorts`. The observed object count was zero at the time of inspection; this is not a permanent assumption and runtime inventory is still required.
