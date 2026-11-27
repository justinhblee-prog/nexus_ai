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

    def test_workspace_transfer_endpoint_uses_verified_request_context(self):
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/transfer-ownership"', self.api)
        self.assertIn("req: WorkspaceOwnershipTransferReq", self.api)
        self.assertIn('client.rpc("transfer_workspace_ownership"', self.api)
        self.assertIn('"p_new_owner_id": str(req.new_owner_id)', self.api)
        self.assertIn("_hosted_rest_client(request)", self.api)

    def test_account_deletion_preflight_is_read_only_and_reports_shared_owner_blockers(self):
        self.assertIn('"/api/hosted/account/deletion/preflight"', self.api)
        self.assertIn('"user_id": f"eq.{user_id}"', self.api)
        self.assertIn('"Transfer workspace ownership to an existing admin before account deletion."', self.api)
        self.assertIn('"account_deletion_enabled": False', self.api)
        self.assertIn("list_account_deletion_storage_objects(user_id", self.api)
        self.assertIn('"shared_workspace_object_blockers": shared_storage_count', self.api)
        self.assertIn('"storage_clear": shared_storage_count == 0', self.api)
        self.assertIn('"preflight_clear": not blockers', self.api)
        self.assertIn("Re-upload or safely transfer those files", self.api)
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/members"', self.api)
        self.assertIn('"/api/hosted/workspaces/{workspace_id}/members/{member_id}/role"', self.api)
        self.assertIn('Field(pattern="^(admin|editor|viewer)$")', self.api)
        self.assertIn("The current owner role cannot be changed here", self.api)

    def test_rpc_client_is_allowlisted_and_uses_user_token(self):
        self.assertIn('_ALLOWED_RPCS = {"transfer_workspace_ownership"}', self.rest)
        self.assertIn('if name not in _ALLOWED_RPCS:', self.rest)
        self.assertIn('"Authorization": f"Bearer {self.access_token}"', self.rest)
        self.assertNotIn("NEXUS_SUPABASE_SERVICE_ROLE_KEY", self.rest)


if __name__ == "__main__":
    unittest.main()
