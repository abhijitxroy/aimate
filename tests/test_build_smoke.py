import io
import unittest
from unittest.mock import Mock, patch
from tools.build_smoke import check_server


class SmokeTests(unittest.TestCase):
    def test_startup_reset_is_retried_then_interface_assets_are_verified(self):
        opener = Mock()
        opener.open.side_effect = [
            ConnectionResetError("Server is starting"),
            io.BytesIO(b'{"status":"ok"}'),
            io.BytesIO(b'<textarea id="question"></textarea><script src="/static/app.js"></script>'),
            io.BytesIO(b"/* App asset */"),
        ]
        with patch("tools.build_smoke.build_opener", return_value=opener), patch("tools.build_smoke.time.sleep") as wait:
            check_server("http://127.0.0.1:18765")
        self.assertEqual(opener.open.call_count, 4)
        self.assertEqual([call.args[0] for call in opener.open.call_args_list],
                         ["http://127.0.0.1:18765/healthz"] * 2 +
                         ["http://127.0.0.1:18765/", "http://127.0.0.1:18765/static/app.js"])
        wait.assert_called_once_with(.25)

    def test_permanent_startup_failure_still_fails_at_deadline(self):
        opener = Mock()
        opener.open.side_effect = ConnectionResetError("Never healthy")
        with patch("tools.build_smoke.build_opener", return_value=opener), patch(
                "tools.build_smoke.time.monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(ValueError, "did not become healthy"):
                check_server("http://127.0.0.1:18765")
        self.assertEqual(opener.open.call_count, 1)

    def test_non_loopback_targets_rejected_without_requests(self):
        with patch("tools.build_smoke.build_opener") as opener:
            for target in ("https://127.0.0.1", "http://example.com", "http://127.0.0.1/path",
                           "http://user:password@127.0.0.1", "http://127.0.0.1?next=example"):
                with self.assertRaisesRegex(ValueError, "127.0.0.1 origin"):
                    check_server(target)
        opener.assert_not_called()
