"""Route fallback semantics: which upstream statuses rotate to the next provider.

404 must trigger a provider switch (model existence is provider-level, not
key-level), while other 4xx (bad request / auth / rate limit) must not.
"""

import unittest

from app.services.proxy_runtime.response_handler import (
    _is_key_retryable_status,
    _is_route_fallback_status,
)


class RouteFallbackStatusTests(unittest.TestCase):
    def test_5xx_triggers_provider_fallback(self):
        for code in (500, 502, 503, 504, 529):
            self.assertTrue(_is_route_fallback_status(code), code)

    def test_404_model_not_found_triggers_provider_fallback(self):
        self.assertTrue(_is_route_fallback_status(404))

    def test_other_client_errors_do_not_trigger_provider_fallback(self):
        for code in (200, 400, 401, 402, 403, 408, 409, 422, 429):
            self.assertFalse(_is_route_fallback_status(code), code)

    def test_key_retryable_statuses_unchanged(self):
        """401/403/429/529 stay key-level: rotate keys before providers."""
        for code in (401, 403, 429, 529):
            self.assertTrue(_is_key_retryable_status(code), code)
        for code in (400, 404, 500):
            self.assertFalse(_is_key_retryable_status(code), code)

    def test_proxy_loop_uses_route_fallback_guard(self):
        """The proxy retry loop must branch on _is_route_fallback_status."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "services" / "proxy.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("if _is_route_fallback_status(status_code):", src)


if __name__ == "__main__":
    unittest.main()
