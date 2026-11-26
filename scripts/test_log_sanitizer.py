#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sanitize_runner_log import sanitize_line

class SanitizerTests(unittest.TestCase):
    def assert_secret_removed(self, line: str, secret: str) -> None:
        safe = sanitize_line(line)
        self.assertNotIn(secret, safe)
        self.assertIn("[REDACTED]", safe)

    def test_environment_style_secret_assignment(self):
        self.assert_secret_removed(
            "BITGET_DEMO_API_SECRET=super-secret-value",
            "super-secret-value"
        )

    def test_quoted_json_api_key_field(self):
        self.assert_secret_removed(
            '{"apiKey": "json-api-key-secret"}',
            "json-api-key-secret"
        )

    def test_quoted_control_plane_token_field(self):
        self.assert_secret_removed(
            "'CONTROL_PLANE_TOKEN': 'control-plane-secret'",
            "control-plane-secret"
        )

    def test_exchange_auth_headers(self):
        self.assert_secret_removed(
            "ACCESS-KEY: exchange-key-secret",
            "exchange-key-secret"
        )
        self.assert_secret_removed(
            "ACCESS-SIGN=exchange-signature-secret",
            "exchange-signature-secret"
        )

    def test_telegram_bot_url(self):
        safe = sanitize_line(
            "POST https://api.telegram.org/bot123456:telegram-secret/sendMessage"
        )
        self.assertNotIn("telegram-secret", safe)
        self.assertNotIn("123456", safe)
        self.assertIn("[REDACTED]", safe)

    def test_signed_query_and_bearer_tokens(self):
        line = "url?sign=query-signature-secret Authorization: Bearer bearer-token-secret"
        safe = sanitize_line(line)
        self.assertNotIn("query-signature-secret", safe)
        self.assertNotIn("bearer-token-secret", safe)

    def test_private_key_and_webhook_query_fields(self):
        self.assert_secret_removed(
            '{"private_key": "private-key-value"}',
            "private-key-value"
        )
        self.assert_secret_removed(
            "https://example.invalid/callback?hook=webhook-secret",
            "webhook-secret"
        )
        self.assert_secret_removed(
            "https://example.invalid/callback?access_key=access-key-value",
            "access-key-value"
        )

    def test_bare_apps_script_deployment_url(self):
        safe = sanitize_line(
            "Redirected to https://script.google.com/macros/s/deployment-id-secret/exec"
        )
        self.assertNotIn("deployment-id-secret", safe)
        self.assertIn("[REDACTED]", safe)

    def test_ansi_and_long_lines_are_bounded(self):
        safe = sanitize_line("\x1b[31m" + ("x" * 2000) + "\x1b[0m")
        self.assertNotIn("\x1b", safe)
        self.assertLessEqual(len(safe), 1200)

if __name__ == "__main__":
    unittest.main(verbosity=2)
