from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VercelFastApiEntrypointTests(unittest.TestCase):
    def test_vercel_uses_fastapi_entrypoint_without_replacing_streamlit_app(self):
        entrypoint = (ROOT / "vercel_entrypoint.py").read_text(encoding="utf-8")
        config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        streamlit_app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('os.environ["NEXUS_HOSTED_AUTH_ENABLED"] = "true"', entrypoint)
        self.assertIn("from api_server import app", entrypoint)
        self.assertIn('entrypoint = "vercel_entrypoint:app"', config)
        self.assertIn("import streamlit as st", streamlit_app)

    def test_hosted_startup_skips_local_sqlite_and_output_directory_writes(self):
        api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        startup_start = api.index('@app.on_event("startup")')
        startup_end = api.index("\nclass LoginReq", startup_start)
        startup = api[startup_start:startup_end]
        self.assertLess(startup.index("if is_hosted_auth_enabled():"), startup.index("init_app_db()"))
        self.assertIn("return", startup[startup.index("if is_hosted_auth_enabled():"):])
        output_start = api.index("# Local filesystem output is used only")
        output_end = api.index("\nRADAR_INTERVAL_SEC", output_start)
        output_setup = api[output_start:output_end]
        self.assertIn("if not is_hosted_auth_enabled():", output_setup)
        self.assertIn('app.mount("/output"', output_setup)

    def test_hosted_workers_remain_opt_in(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('NEXUS_HOSTED_WORKER_ENABLED: ${NEXUS_HOSTED_WORKER_ENABLED:-false}', compose)
        self.assertIn('NEXUS_HOSTED_UPLOAD_ENABLED: ${NEXUS_HOSTED_UPLOAD_ENABLED:-false}', compose)


if __name__ == "__main__":
    unittest.main()
