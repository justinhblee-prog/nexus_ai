from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalOperationsScriptContractTests(unittest.TestCase):
    def test_setup_script_generates_or_preserves_local_secrets_without_printing_them(self):
        script = (ROOT / "scripts" / "setup-local-nexus.ps1").read_text(encoding="utf-8")
        self.assertIn("Read-Host", script)
        self.assertIn("SecureString", script)
        self.assertIn("NEXUS_SESSION_SECRET", script)
        self.assertIn("NEXUS_AUTH_ENABLED=true", script)
        self.assertIn("docker compose config --quiet", script)
        self.assertNotIn("Write-Host $Password", script)
        self.assertNotIn("Write-Output $Secret", script)

    def test_verification_script_checks_auth_health_and_real_renderer(self):
        script = (ROOT / "scripts" / "verify-local-nexus.ps1").read_text(encoding="utf-8")
        for required in (
            "/api/session/status",
            "/api/overview",
            "/output/session-guard-check.mp4",
            "/_stcore/health",
            "unittest discover -s tests",
            "unittest discover -s integration_tests",
            "scripts/check-feed-connectivity.py",
        ):
            with self.subTest(required=required):
                self.assertIn(required, script)

    def test_local_scripts_do_not_remove_data_or_rewrite_git_history(self):
        for name in ("setup-local-nexus.ps1", "verify-local-nexus.ps1"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
            for forbidden in (
                "docker compose down -v",
                "docker volume prune",
                "git clean -xfd",
                "git push --force",
                "remove-item -recurse",
                "rm -rf",
            ):
                with self.subTest(script=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
