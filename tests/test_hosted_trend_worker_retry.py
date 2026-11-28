import os
import unittest
from unittest.mock import Mock, call, patch

import hosted_trend_worker as worker


class StopPolling(Exception):
    pass


class HostedTrendWorkerRetryTests(unittest.TestCase):
    def test_transient_scan_failure_waits_then_retries_without_recreating_admin_client(self):
        admin = Mock()
        with patch.dict(os.environ, {
            "NEXUS_TREND_WORKER_ENABLED": "true",
            "NEXUS_TREND_WORKER_POLL_SECONDS": "21600",
        }), patch.object(worker, "SupabaseAdminRestClient", return_value=admin) as factory, \
             patch.object(
                 worker,
                 "run_once",
                 side_effect=[RuntimeError("temporary upstream failure"), {"daily": 4, "weekly": 2}],
             ) as run_once, \
             patch.object(worker.time, "sleep", side_effect=[None, StopPolling]) as sleep:
            with self.assertRaises(StopPolling):
                worker.run_worker()

        factory.assert_called_once_with()
        self.assertEqual(run_once.call_count, 2)
        self.assertEqual(run_once.call_args_list, [call(admin=admin), call(admin=admin)])
        self.assertEqual(sleep.call_args_list, [call(21600), call(21600)])


if __name__ == "__main__":
    unittest.main()
