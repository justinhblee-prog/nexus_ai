import unittest
import hashlib
from unittest.mock import call, patch, Mock

from token_vault import TokenVaultError
from supabase_admin import SupabaseAdminError

from account_deletion_worker import (
    AccountDeletionBlocked,
    _cleanup_oauth,
    _inventory_storage,
    _workspace_plan,
    process_one_account_deletion,
)


USER = "11111111-1111-4111-8111-111111111111"
SOLE = "wsp_22222222-2222-4222-8222-222222222222"
SHARED = "wsp_33333333-3333-4333-8333-333333333333"


class AccountDeletionWorkerTests(unittest.TestCase):
    def test_workspace_plan_deletes_only_sole_owned_workspace(self):
        admin = Mock()
        admin.list_account_user_memberships.return_value = [
            {"workspace_id": SOLE, "role": "owner"},
            {"workspace_id": SHARED, "role": "admin"},
        ]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.side_effect = [
            [{"user_id": USER, "role": "owner"}],
            [{"user_id": USER, "role": "admin"}, {"user_id": "44444444-4444-4444-8444-444444444444", "role": "owner"}],
        ]
        deleting, shared = _workspace_plan(admin, USER)
        self.assertEqual(deleting, [SOLE])
        self.assertEqual(shared, [SHARED])

    def test_workspace_owner_with_other_members_is_blocked(self):
        admin = Mock()
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [
            {"user_id": USER, "role": "owner"},
            {"user_id": "44444444-4444-4444-8444-444444444444", "role": "admin"},
        ]
        with self.assertRaises(AccountDeletionBlocked) as caught:
            _workspace_plan(admin, USER)
        self.assertEqual(caught.exception.code, "workspace_ownership_transfer_required")

    def test_storage_inventory_blocks_shared_and_unclassified_objects(self):
        admin = Mock()
        admin.list_account_deletion_storage_objects.return_value = [{
            "bucket_id": "nexus-shorts", "name": f"{SHARED}/job/video.mp4",
        }]
        admin.list_account_personal_gallery_images.return_value = []
        with self.assertRaises(AccountDeletionBlocked) as caught:
            _inventory_storage(admin, USER, [SOLE], [SHARED])
        self.assertEqual(caught.exception.code, "shared_workspace_storage_found")

        admin.list_account_deletion_storage_objects.return_value = [{
            "bucket_id": "nexus-shorts", "name": "unknown-folder/file.mp4",
        }]
        with self.assertRaises(AccountDeletionBlocked) as caught:
            _inventory_storage(admin, USER, [SOLE], [SHARED])
        self.assertEqual(caught.exception.code, "unclassified_storage_object_found")

    def test_storage_inventory_rejects_duplicate_bucket_names(self):
        admin = Mock()
        admin.list_account_deletion_storage_objects.return_value = [
            {"bucket_id": "acs-assets", "name": f"{SOLE}/asset/file.bin"},
            {"bucket_id": "acs-gallery", "name": f"{SOLE}/asset/file.bin"},
        ]
        admin.list_account_personal_gallery_images.return_value = []
        with self.assertRaises(AccountDeletionBlocked) as caught:
            _inventory_storage(admin, USER, [SOLE], [])
        self.assertEqual(caught.exception.code, "ambiguous_storage_object_bucket")

    def test_oauth_grant_used_by_other_workspace_is_not_revoked(self):
        admin = Mock()
        admin.list_youtube_connections_for_workspaces.return_value = [{
            "connection_id": "55555555-5555-4555-8555-555555555555",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        admin.get_account_deletion_oauth_state.return_value = None
        admin.set_account_deletion_oauth_state.return_value = "preserved"
        admin.has_active_connection_outside_workspaces.return_value = True
        _cleanup_oauth(admin, USER, [SOLE], oauth_config_factory=Mock(), decrypt_token=Mock())
        admin.get_credential.assert_not_called()
        admin.delete_credential.assert_called_once()

    def test_oauth_grant_without_external_workspace_is_revoked_and_credentials_removed(self):
        admin = Mock()
        admin.list_youtube_connections_for_workspaces.return_value = [
            {"connection_id": "55555555-5555-4555-8555-555555555555", "provider_account_id": "google-account", "status": "connected"},
            {"connection_id": "66666666-6666-4666-8666-666666666666", "provider_account_id": "google-account", "status": "connected"},
        ]
        admin.get_account_deletion_oauth_state.return_value = None
        admin.set_account_deletion_oauth_state.side_effect = ["revocation_started", "revoked"]
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.get_credential.side_effect = [
            {"encrypted_refresh_token_hex": "ciphertext", "encryption_key_version": "v1"},
            {"encrypted_refresh_token_hex": "ciphertext-2", "encryption_key_version": "v1"},
        ]
        oauth = Mock()
        config_factory = Mock(return_value=oauth)
        decrypt = Mock(return_value="refresh-token")
        _cleanup_oauth(admin, USER, [SOLE], oauth_config_factory=config_factory, decrypt_token=decrypt)
        oauth.revoke_refresh_token.assert_called_once_with("refresh-token")
        self.assertEqual(admin.delete_credential.call_count, 2)

    def test_oauth_revocation_state_makes_retry_skip_completed_provider_call(self):
        admin = Mock()
        admin.list_youtube_connections_for_workspaces.return_value = [{
            "connection_id": "55555555-5555-4555-8555-555555555555",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        admin.get_account_deletion_oauth_state.side_effect = [None, "revoked"]
        admin.set_account_deletion_oauth_state.side_effect = ["revocation_started", "revoked"]
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.get_credential.return_value = {
            "encrypted_refresh_token_hex": "ciphertext",
            "encryption_key_version": "v1",
        }
        oauth = Mock()
        decrypt = Mock(return_value="refresh-token")
        fingerprint = hashlib.sha256(b"google-account").hexdigest()

        _cleanup_oauth(admin, USER, [SOLE], Mock(return_value=oauth), decrypt)
        _cleanup_oauth(admin, USER, [SOLE], Mock(return_value=oauth), decrypt)

        oauth.revoke_refresh_token.assert_called_once_with("refresh-token")
        self.assertEqual(admin.set_account_deletion_oauth_state.call_args_list, [
            call(USER, fingerprint, "revocation_started"),
            call(USER, fingerprint, "revoked"),
        ])
        self.assertEqual(admin.delete_credential.call_count, 2)

    def test_oauth_revocation_is_not_repeated_after_storage_failure_retry(self):
        admin = Mock()
        request = {"user_id": USER, "sessions_revoked": True}
        admin.claim_next_account_deletion_request.side_effect = [request, request]
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [{"user_id": USER, "role": "owner"}]
        admin.list_account_deletion_active_leases.return_value = []
        storage_object = {"bucket_id": "nexus-shorts", "name": f"{SOLE}/jobs/video.mp4"}
        admin.list_account_deletion_storage_objects.side_effect = [[storage_object], [storage_object], [], []]
        admin.list_account_personal_gallery_images.return_value = []
        admin.list_youtube_connections_for_workspaces.return_value = [{
            "connection_id": "55555555-5555-4555-8555-555555555555",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.get_account_deletion_oauth_state.side_effect = [None, "revoked"]
        admin.set_account_deletion_oauth_state.side_effect = ["revocation_started", "revoked"]
        admin.get_credential.return_value = {
            "encrypted_refresh_token_hex": "ciphertext",
            "encryption_key_version": "v1",
        }
        admin.delete_storage_object_in_bucket.side_effect = [
            SupabaseAdminError("temporary storage failure"),
            True,
        ]
        admin.account_user_reference_counts.return_value = {}
        admin.count_account_private_user_rows.return_value = {}
        admin.update_account_deletion_request.return_value = True
        oauth = Mock()
        oauth_factory = Mock(return_value=oauth)
        decrypt = Mock(return_value="refresh-token")

        self.assertTrue(process_one_account_deletion(
            admin, "worker-1", oauth_config_factory=oauth_factory, decrypt_token=decrypt
        ))
        self.assertTrue(process_one_account_deletion(
            admin, "worker-1", oauth_config_factory=oauth_factory, decrypt_token=decrypt
        ))

        oauth.revoke_refresh_token.assert_called_once_with("refresh-token")
        admin.get_credential.assert_called_once()
        self.assertEqual(admin.delete_credential.call_count, 2)
        admin.delete_account_workspace.assert_called_once_with(SOLE)
        admin.delete_auth_user.assert_called_once_with(USER)
        self.assertEqual(
            [call.args[2:4] for call in admin.update_account_deletion_request.call_args_list],
            [("retry", "storage_cleanup"), ("completed", "complete")],
        )

    def test_oauth_cleanup_fails_closed_when_revocation_intent_is_not_persisted(self):
        admin = Mock()
        admin.list_youtube_connections_for_workspaces.return_value = [{
            "connection_id": "55555555-5555-4555-8555-555555555555",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        admin.get_account_deletion_oauth_state.return_value = None
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.set_account_deletion_oauth_state.return_value = None
        oauth = Mock()

        with self.assertRaises(SupabaseAdminError):
            _cleanup_oauth(admin, USER, [SOLE], Mock(return_value=oauth), Mock())

        oauth.revoke_refresh_token.assert_not_called()
        admin.get_credential.assert_not_called()
        admin.delete_credential.assert_not_called()

    def test_oauth_cleanup_tries_another_credential_when_one_ciphertext_is_invalid(self):
        admin = Mock()
        admin.list_youtube_connections_for_workspaces.return_value = [
            {"connection_id": "55555555-5555-4555-8555-555555555555", "provider_account_id": "google-account", "status": "connected"},
            {"connection_id": "66666666-6666-4666-8666-666666666666", "provider_account_id": "google-account", "status": "connected"},
        ]
        admin.get_account_deletion_oauth_state.return_value = None
        admin.set_account_deletion_oauth_state.side_effect = ["revocation_started", "revoked"]
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.get_credential.side_effect = [
            {"encrypted_refresh_token_hex": "bad-ciphertext", "encryption_key_version": "v1"},
            {"encrypted_refresh_token_hex": "good-ciphertext", "encryption_key_version": "v1"},
        ]
        oauth = Mock()
        decrypt = Mock(side_effect=[TokenVaultError("bad"), "valid-refresh-token"])
        _cleanup_oauth(admin, USER, [SOLE], oauth_config_factory=Mock(return_value=oauth), decrypt_token=decrypt)
        oauth.revoke_refresh_token.assert_called_once_with("valid-refresh-token")

    def test_active_worker_lease_retries_before_any_destructive_action(self):
        admin = Mock()
        admin.claim_next_account_deletion_request.return_value = {
            "user_id": USER, "sessions_revoked": True,
        }
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [{"user_id": USER, "role": "owner"}]
        admin.list_account_deletion_active_leases.return_value = [{"lease_kind": "render"}]
        admin.update_account_deletion_request.return_value = True
        self.assertTrue(process_one_account_deletion(admin, "worker-1"))
        admin.heartbeat_account_deletion_worker.assert_called_once_with("worker-1")
        admin.delete_account_workspace.assert_not_called()
        admin.delete_storage_object_in_bucket.assert_not_called()
        admin.update_account_deletion_request.assert_called_once_with(
            USER, "worker-1", "retry", "worker_lease_check", "active_worker_leases", 120
        )

    def test_successful_cleanup_verifies_all_references_before_auth_deletion(self):
        admin = Mock()
        admin.claim_next_account_deletion_request.return_value = {
            "user_id": USER, "sessions_revoked": True,
        }
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [{"user_id": USER, "role": "owner"}]
        admin.list_account_deletion_active_leases.return_value = []
        admin.list_account_deletion_storage_objects.return_value = []
        admin.list_account_personal_gallery_images.return_value = []
        admin.list_youtube_connections_for_workspaces.return_value = []
        admin.account_user_reference_counts.return_value = {}
        admin.count_account_private_user_rows.return_value = {}
        admin.update_account_deletion_request.return_value = True

        self.assertTrue(process_one_account_deletion(admin, "worker-1"))
        admin.delete_account_workspace_generation_jobs.assert_called_once_with([SOLE])
        admin.delete_account_workspace.assert_called_once_with(SOLE)
        admin.delete_auth_user.assert_called_once_with(USER)
        self.assertEqual(admin.update_account_deletion_request.call_args.args[2:4], ("completed", "complete"))
        self.assertEqual(
            admin.list_account_deletion_storage_objects.call_args.kwargs["workspace_ids"],
            [SOLE],
        )


    def test_partial_storage_cleanup_failure_is_retryable_before_identity_deletion(self):
        admin = Mock()
        admin.claim_next_account_deletion_request.return_value = {
            "user_id": USER, "sessions_revoked": True,
        }
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [{"user_id": USER, "role": "owner"}]
        admin.list_account_deletion_active_leases.return_value = []
        admin.list_account_deletion_storage_objects.return_value = [{
            "bucket_id": "nexus-shorts", "name": f"{SOLE}/jobs/video.mp4",
        }]
        admin.list_account_personal_gallery_images.return_value = []
        admin.list_youtube_connections_for_workspaces.return_value = []
        admin.delete_storage_object_in_bucket.side_effect = SupabaseAdminError("temporary storage failure")
        admin.update_account_deletion_request.return_value = True

        self.assertTrue(process_one_account_deletion(admin, "worker-1"))
        admin.delete_storage_object_in_bucket.assert_called_once_with(
            "nexus-shorts", f"{SOLE}/jobs/video.mp4"
        )
        admin.delete_account_workspace.assert_not_called()
        admin.delete_account_profile.assert_not_called()
        admin.delete_auth_user.assert_not_called()
        admin.update_account_deletion_request.assert_called_once_with(
            USER, "worker-1", "retry", "storage_cleanup", "supabaseadminerror", 120
        )

    def test_oauth_revocation_failure_preserves_credentials_and_retries(self):
        from youtube_oauth import GoogleOAuthError

        admin = Mock()
        admin.claim_next_account_deletion_request.return_value = {
            "user_id": USER, "sessions_revoked": True,
        }
        admin.list_account_user_memberships.return_value = [{"workspace_id": SOLE, "role": "owner"}]
        admin.list_account_owned_workspaces.return_value = [{"workspace_id": SOLE, "owner_id": USER}]
        admin.list_account_workspace_members.return_value = [{"user_id": USER, "role": "owner"}]
        admin.list_account_deletion_active_leases.return_value = []
        admin.list_account_deletion_storage_objects.return_value = []
        admin.list_account_personal_gallery_images.return_value = []
        admin.list_youtube_connections_for_workspaces.return_value = [{
            "connection_id": "55555555-5555-4555-8555-555555555555",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        admin.has_active_connection_outside_workspaces.return_value = False
        admin.get_account_deletion_oauth_state.return_value = None
        admin.set_account_deletion_oauth_state.return_value = "revocation_started"
        admin.get_credential.return_value = {
            "encrypted_refresh_token_hex": "ciphertext",
            "encryption_key_version": "v1",
        }
        admin.update_account_deletion_request.return_value = True
        oauth = Mock()
        oauth.revoke_refresh_token.side_effect = GoogleOAuthError("temporary provider failure")

        self.assertTrue(process_one_account_deletion(
            admin,
            "worker-1",
            oauth_config_factory=Mock(return_value=oauth),
            decrypt_token=Mock(return_value="refresh-token"),
        ))
        oauth.revoke_refresh_token.assert_called_once_with("refresh-token")
        admin.delete_credential.assert_not_called()
        admin.delete_storage_object_in_bucket.assert_not_called()
        admin.delete_account_workspace.assert_not_called()
        admin.delete_auth_user.assert_not_called()
        admin.update_account_deletion_request.assert_called_once_with(
            USER, "worker-1", "retry", "oauth_cleanup", "googleoautherror", 120
        )


if __name__ == "__main__":
    unittest.main()
