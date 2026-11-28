import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"


class AccountDeletionComposeTests(unittest.TestCase):
    def test_api_and_worker_share_explicit_disabled_by_default_gate(self):
        source = COMPOSE.read_text(encoding="utf-8")
        api_service = source.split("  hosted-render-worker:", 1)[0]
        worker_service = source.split("  hosted-account-deletion-worker:", 1)[1].split("  hosted-upload-worker:", 1)[0]
        expected = "NEXUS_ACCOUNT_DELETION_WORKER_ENABLED: ${NEXUS_ACCOUNT_DELETION_WORKER_ENABLED:-false}"
        self.assertIn(expected, api_service)
        self.assertIn(expected, worker_service)
        self.assertIn("NEXUS_ACCOUNT_DELETION_ENABLED: ${NEXUS_ACCOUNT_DELETION_ENABLED:-false}", api_service)


if __name__ == "__main__":
    unittest.main()
