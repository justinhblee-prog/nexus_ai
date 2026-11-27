# NEXUS account deletion and workspace ownership policy

## Current status

Account deletion is a required SaaS capability, but the destructive Auth deletion endpoint is intentionally not exposed yet. The account-lifecycle work in this PR establishes the safe ownership-transfer and audit-preservation prerequisites. No production migration or user deletion has been executed.

## Workspace rules

1. A user may leave a workspace where they are a member without deleting that workspace.
2. A workspace owner must transfer ownership to an existing admin before deleting their account when other members remain.
3. The transfer operation changes the workspace owner and membership roles atomically: the selected admin becomes `owner`, and the previous owner becomes `admin`.
4. The transfer function derives the acting user from `auth.uid()`; caller-supplied identity is never trusted.
5. A sole-member workspace may be removed as part of the account deletion workflow. A shared workspace must never be cascade-deleted merely because its former owner account is removed.

## Shared workspace records

Shorts jobs, channels, assets, connections, and review events may outlive the person who created them. Their author/reviewer foreign keys are nullable and use `ON DELETE SET NULL`, preserving the workspace content and audit event while removing the deleted identity reference.

## Required deletion saga (not yet implemented)

The eventual server-only deletion workflow must be idempotent and resumable:

1. Require a fresh reauthentication step and an explicit account-deletion confirmation.
2. Block deletion while the user owns any workspace with other members. Return the workspace IDs and require ownership transfer first.
3. Mark the account as deletion-pending and prevent new workspace writes/jobs for that user.
4. Stop or cancel the user's pending work and wait for active render/upload leases to finish or expire safely.
5. Revoke each connected provider grant where the deleted user is the credential owner; remove encrypted refresh-token records even when provider revocation fails, and record the revocation outcome without storing token material.
6. Enumerate and delete Storage objects owned by the user, including objects in all NEXUS buckets. Do not delete Storage metadata rows directly; use the Storage API.
7. Delete the user's sole-member workspaces and their workspace-scoped records. Preserve all shared workspaces and their content.
8. Remove any remaining user-owned personal assets according to the product retention policy.
9. Revoke sessions and delete the Auth user through the Supabase Auth Admin API.
10. Verify no user-owned Storage objects, OAuth credentials, workspace ownership, or user foreign-key references remain. Mark the deletion request complete only after verification.

If any external cleanup fails, retain a retryable deletion-pending record and do not report completion. Do not partially delete the Auth identity while required cleanup is still outstanding.

## Explicit safety constraints

- Never cascade-delete a shared workspace.
- Never delete another member's content or YouTube connection.
- Never expose service-role credentials or OAuth tokens to the browser.
- Never treat an HTTP success from the Auth Admin API as proof that Storage and provider credentials were cleaned.
- Account deletion is not complete until the verification step succeeds.
