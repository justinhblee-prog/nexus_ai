import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "api_server.py"
REST = ROOT / "supabase_rest.py"


class AccountLifecycleApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = API.read_text(encoding="utf-8")
        cls.rest = REST.read_text(encoding="utf-8")

    def test_recent_password_reauthentication_uses_verified_amr_timestamp(self):
        self.assertIn("def has_recent_password_reauthentication(user", self.api)
        self.assertIn('entry.get("method") != "password"', self.api)
        self.assertIn('current - max_age_seconds <= timestamp <= current + 30', self.api)
        self.assertIn("has_recent_password_reauthentication(user)", self.api)

    def test_workspace_transfer_endpoint_uses_verified_request_context(self):
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/transfer-ownership"', self.api)
        self.assertIn("req: WorkspaceOwnershipTransferReq", self.api)
        self.assertIn('client.rpc("transfer_workspace_ownership"', self.api)
        self.assertIn('"p_new_owner_id": str(req.new_owner_id)', self.api)
        self.assertIn("_hosted_rest_client(request)", self.api)
        self.assertIn('"is_account_deletion_tombstoned"', self.rest)
        self.assertIn("This account is no longer active", self.api)

    def test_account_deletion_preflight_is_read_only_and_reports_shared_owner_blockers(self):
        self.assertIn('"/api/hosted/account/deletion/preflight"', self.api)
        self.assertIn('"user_id": f"eq.{user_id}"', self.api)
        self.assertIn('"Transfer workspace ownership to an existing admin before account deletion."', self.api)
        self.assertIn('"account_deletion_enabled": worker_online', self.api)
        self.assertIn("admin.is_account_deletion_worker_online()", self.api)
        self.assertIn('if not preflight.get("account_deletion_enabled")', self.api)
        self.assertIn('"/api/hosted/account/deletion/request"', self.api)
        self.assertIn('Field(pattern="^DELETE MY ACCOUNT$")', self.api)
        self.assertIn("has_recent_password_reauthentication(user)", self.api)
        self.assertIn("admin.enqueue_account_deletion(user_id", self.api)
        self.assertIn("admin.revoke_user_sessions(request.state.hosted_access_token)", self.api)
        self.assertIn("admin.mark_account_deletion_sessions_revoked(user_id)", self.api)
        self.assertIn("list_account_deletion_storage_objects(user_id", self.api)
        self.assertIn("workspace_ids=deletion_workspace_ids", self.api)
        self.assertIn('"unclassified_object_blockers": unclassified_storage_count', self.api)
        self.assertIn("Map or remove them before account deletion", self.api)
        self.assertIn("list_account_deletion_active_leases(deletion_workspace_ids)", self.api)
        self.assertIn("list_youtube_connections_for_workspaces(deletion_workspace_ids)", self.api)
        self.assertIn('"provider_grants_preserved_for_other_workspaces": shared_provider_grants_preserved', self.api)
        self.assertIn("has_active_connection_outside_workspaces(", self.api)
        self.assertIn("seen_provider_accounts = set()", self.api)
        self.assertIn('"active_worker_lease_count": len(active_leases)', self.api)
        self.assertIn('"shared_workspace_object_blockers": shared_storage_count', self.api)
        self.assertIn('"storage_clear": shared_storage_count == 0 and unclassified_storage_count == 0', self.api)
        self.assertIn('"preflight_clear": not blockers', self.api)
        self.assertIn("Re-upload or safely transfer those files", self.api)
        self.assertIn("if others or not is_owner:", self.api)
        self.assertIn('"member_count": len(members) if is_owner else None', self.api)
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/members"', self.api)
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/members/{member_id}/role"', self.api)
        self.assertIn('Field(pattern="^(admin|editor|viewer)$")', self.api)
        self.assertIn("The current owner role cannot be changed here", self.api)

    def test_tombstoned_account_can_retry_only_existing_request_without_rerunning_preflight(self):
        self.assertIn('request.state.account_deletion_tombstoned = bool(', self.api)
        self.assertIn('if not (path == "/api/hosted/account/deletion/request" and request.method == "POST"):', self.api)
        self.assertIn('return JSONResponse(status_code=401, content={"detail": "This account is no longer active"})', self.api)
        self.assertIn('if getattr(request.state, "account_deletion_tombstoned", False):', self.api)
        self.assertIn("queued = admin.get_account_deletion_request(user_id)", self.api)
        self.assertIn('raise SupabaseAdminError("Existing tombstone has no verifiable deletion request")', self.api)
        self.assertIn("else:\n            preflight = hosted_account_deletion_preflight(request)", self.api)
        self.assertIn('if not queued.get("sessions_revoked"):', self.api)
        self.assertIn("admin.revoke_user_sessions(request.state.hosted_access_token)", self.api)
        self.assertIn("admin.mark_account_deletion_sessions_revoked(user_id)", self.api)

    def test_youtube_disconnect_persists_revocation_checkpoint_before_provider_call(self):
        start = self.api.index('def hosted_youtube_disconnect(')
        end = self.api.index('@app.get("/api/hosted/jobs/{job_id}/preview")', start)
        route = self.api[start:end]
        self.assertIn("admin.get_youtube_disconnect_state(connection_key)", route)
        self.assertIn('admin.set_youtube_disconnect_state(connection_key, "revocation_started")', route)
        self.assertIn('admin.set_youtube_disconnect_state(connection_key, "revoked")', route)
        self.assertLess(route.index('"revocation_started"'), route.index("revoke_refresh_token(refresh_token)"))
        self.assertIn('elif revocation_state == "revocation_started":', route)
        self.assertIn("credential retained for safe retry", route)
        self.assertIn("admin.update_connection(str(connection_id), workspace_id", route)
        self.assertIn("admin.delete_credential(str(connection_id))", route)

    def test_rpc_client_is_allowlisted_and_uses_user_token(self):
        self.assertIn('_ALLOWED_RPCS = {"transfer_workspace_ownership", "is_account_deletion_tombstoned"}', self.rest)
        self.assertIn('if name not in _ALLOWED_RPCS:', self.rest)
        self.assertIn('"Authorization": f"Bearer {self.access_token}"', self.rest)
        self.assertNotIn("NEXUS_SUPABASE_SERVICE_ROLE_KEY", self.rest)


if __name__ == "__main__":
    unittest.main()
