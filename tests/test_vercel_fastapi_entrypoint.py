from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VercelFastApiEntrypointTests(unittest.TestCase):
    def test_vercel_uses_standard_fastapi_entrypoint_without_replacing_streamlit_app(self):
        entrypoint = (ROOT / "vercel_entrypoint.py").read_text(encoding="utf-8")
        vercel_alias = (ROOT / "main.py").read_text(encoding="utf-8")
        config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        streamlit_app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('os.environ["NEXUS_HOSTED_AUTH_ENABLED"] = "true"', entrypoint)
        self.assertIn("from api_server import app", entrypoint)
        self.assertIn("from vercel_entrypoint import app", vercel_alias)
        self.assertIn('entrypoint = "main:app"', config)
        self.assertIn("import streamlit as st", streamlit_app)

    def test_hosted_startup_skips_local_sqlite_and_output_directory_writes(self):
        api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        startup_start = api.index('@app.on_event("startup")')
        startup_end = api.index("\\nclass LoginReq", startup_start)
        startup = api[startup_start:startup_end]
        self.assertLess(startup.index("if is_hosted_auth_enabled():"), startup.index("init_app_db()"))
        self.assertIn("return", startup[startup.index("if is_hosted_auth_enabled():"):])
        output_start = api.index("# Local filesystem output is used only")
        output_end = api.index("\\nRADAR_INTERVAL_SEC", output_start)
        output_setup = api[output_start:output_end]
        self.assertIn("if not is_hosted_auth_enabled():", output_setup)
        self.assertIn('app.mount("/output"', output_setup)

    def test_hosted_workers_remain_opt_in(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('NEXUS_HOSTED_WORKER_ENABLED: ${NEXUS_HOSTED_WORKER_ENABLED:-false}', compose)
        self.assertIn('NEXUS_HOSTED_UPLOAD_ENABLED: ${NEXUS_HOSTED_UPLOAD_ENABLED:-false}', compose)

    def test_hosted_runtime_skips_local_media_and_analytics_imports(self):
        api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("if is_hosted_auth_enabled():", api)
        hosted_start = api.index("if is_hosted_auth_enabled():")
        local_import = api.index("import video_maker, trend_radar, youtube_analytics, yt_uploader", hosted_start)
        self.assertLess(hosted_start, local_import)
        hosted_branch = api[hosted_start:local_import]
        self.assertIn("SimpleNamespace(", hosted_branch)
        self.assertIn('DB_PATH=os.getenv("NEXUS_TREND_RADAR_DB_PATH", "data/studio_data.db")', hosted_branch)
        self.assertNotIn("video_maker", hosted_branch)
        self.assertNotIn("youtube_analytics", hosted_branch)
        self.assertNotIn("yt_uploader", hosted_branch)


if __name__ == "__main__":
    unittest.main()
