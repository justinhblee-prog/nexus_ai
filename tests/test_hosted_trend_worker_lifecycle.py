import os
import unittest
from unittest.mock import Mock, patch

import hosted_trend_worker as worker


class StopPolling(Exception):
    pass


class HostedTrendWorkerLifecycleTests(unittest.TestCase):
    def test_worker_is_disabled_by_default_without_creating_admin_or_scanning(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(worker, "SupabaseAdminRestClient") as admin_factory, \
             patch.object(worker, "run_once") as run_once:
            worker.run_worker()
        admin_factory.assert_not_called()
        run_once.assert_not_called()

    def test_worker_disabled_flag_accepts_false_values(self):
        for value in ("", "0", "false", "no", "off"):
            with self.subTest(value=value), \
                 patch.dict(os.environ, {"NEXUS_TREND_WORKER_ENABLED": value}), \
                 patch.object(worker, "SupabaseAdminRestClient") as admin_factory, \
                 patch.object(worker, "run_once") as run_once:
                worker.run_worker()
                admin_factory.assert_not_called()
                run_once.assert_not_called()

    def test_enabled_worker_clamps_poll_interval_and_runs_one_cycle(self):
        admin = Mock()
        with patch.dict(os.environ, {
            "NEXUS_TREND_WORKER_ENABLED": "true",
            "NEXUS_TREND_WORKER_POLL_SECONDS": "1",
        }), patch.object(worker, "SupabaseAdminRestClient", return_value=admin), \
             patch.object(worker, "run_once", return_value={"daily": 2, "weekly": 3}) as run_once, \
             patch.object(worker.time, "sleep", side_effect=StopPolling) as sleep:
            with self.assertRaises(StopPolling):
                worker.run_worker()
        run_once.assert_called_once_with(admin=admin)
        sleep.assert_called_once_with(3600)

    def test_enabled_worker_caps_excessive_poll_interval(self):
        admin = Mock()
        with patch.dict(os.environ, {
            "NEXUS_TREND_WORKER_ENABLED": "yes",
            "NEXUS_TREND_WORKER_POLL_SECONDS": "999999",
        }), patch.object(worker, "SupabaseAdminRestClient", return_value=admin), \
             patch.object(worker, "run_once", return_value={}) as run_once, \
             patch.object(worker.time, "sleep", side_effect=StopPolling) as sleep:
            with self.assertRaises(StopPolling):
                worker.run_worker()
        run_once.assert_called_once_with(admin=admin)
        sleep.assert_called_once_with(86400)

    def test_invalid_poll_interval_uses_six_hour_default(self):
        admin = Mock()
        with patch.dict(os.environ, {
            "NEXUS_TREND_WORKER_ENABLED": "true",
            "NEXUS_TREND_WORKER_POLL_SECONDS": "not-a-number",
        }), patch.object(worker, "SupabaseAdminRestClient", return_value=admin), \
             patch.object(worker, "run_once", return_value={}) as run_once, \
             patch.object(worker.time, "sleep", side_effect=StopPolling) as sleep:
            with self.assertRaises(StopPolling):
                worker.run_worker()
        run_once.assert_called_once_with(admin=admin)
        sleep.assert_called_once_with(21600)


if __name__ == "__main__":
    unittest.main()
