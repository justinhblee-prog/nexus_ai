"""Exercise FastAPI session protection through a real Uvicorn process."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import requests


class ApiRuntimeIntegrationTests(unittest.TestCase):
    def test_login_cookie_protects_api_and_output_then_logout_revokes_access(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as workspace:
            Path(workspace, "output").mkdir()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]

            env = os.environ.copy()
            env.update({
                "NEXUS_API_PASSWORD": "integration-test-password",
                "NEXUS_SESSION_SECRET": "test-session-secret-" + ("x" * 48),
                "NEXUS_AUTH_ENABLED": "true",
                "NEXUS_COOKIE_SECURE": "false",
                "PYTHONPATH": str(repo_root) + os.pathsep + env.get("PYTHONPATH", ""),
            })
            server_code = (
                "import api_server; "
                "api_server.watch_topics_loop = lambda: None; "
                "api_server.auto_radar_and_scheduler_loop = lambda: None; "
                "import uvicorn; "
                f"uvicorn.run(api_server.app, host='127.0.0.1', port={port}, log_level='error')"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", server_code],
                cwd=workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            base_url = f"http://127.0.0.1:{port}"
            session = requests.Session()
            try:
                deadline = time.time() + 20
                status = None
                while time.time() < deadline:
                    if process.poll() is not None:
                        output = process.stdout.read() if process.stdout else ""
                        self.fail("Uvicorn exited before becoming ready: " + output[-4000:])
                    try:
                        status = session.get(base_url + "/api/session/status", timeout=1)
                        if status.status_code == 200:
                            break
                    except requests.RequestException:
                        time.sleep(0.2)
                self.assertIsNotNone(status, "FastAPI did not become ready")
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json(), {
                    "configured": True, "authenticated": False, "required": True
                })

                self.assertEqual(session.get(base_url + "/api/overview", timeout=3).status_code, 401)
                self.assertEqual(session.get(base_url + "/output/session-guard-check.mp4", timeout=3).status_code, 401)

                wrong = session.post(
                    base_url + "/api/session/login",
                    json={"password": "incorrect-password"},
                    timeout=3,
                )
                self.assertEqual(wrong.status_code, 401)
                self.assertFalse(session.cookies.get("nexus_session"))

                login = session.post(
                    base_url + "/api/session/login",
                    json={"password": "integration-test-password"},
                    timeout=3,
                )
                self.assertEqual(login.status_code, 200)
                cookie_header = login.headers.get("Set-Cookie", "")
                self.assertIn("HttpOnly", cookie_header)
                self.assertIn("SameSite=strict", cookie_header)
                self.assertTrue(session.cookies.get("nexus_session"))

                overview = session.get(base_url + "/api/overview", timeout=5)
                self.assertEqual(overview.status_code, 200)
                self.assertIn("channels", overview.json())
                self.assertGreaterEqual(len(overview.json()["channels"]), 1)

                logout = session.post(base_url + "/api/session/logout", timeout=3)
                self.assertEqual(logout.status_code, 200)
                self.assertFalse(session.cookies.get("nexus_session"))
                self.assertEqual(session.get(base_url + "/api/overview", timeout=3).status_code, 401)
            finally:
                session.close()
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()


if __name__ == "__main__":
    unittest.main()
