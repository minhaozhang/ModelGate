import unittest
from unittest.mock import Mock, patch

from fastapi.responses import HTMLResponse

from app.core import config
from app.routes import auth, pages


class AdminAuthLockoutTests(unittest.TestCase):
    def setUp(self):
        config.login_attempts.clear()
        config.login_lockout.clear()

    def tearDown(self):
        config.login_attempts.clear()
        config.login_lockout.clear()

    def test_admin_login_locks_on_fifth_failed_attempt(self):
        client_ip = "203.0.113.10"

        for attempt in range(1, 5):
            response = auth._record_failure(None, client_ip, "admin")
            self.assertEqual(response.status_code, 401, f"attempt {attempt}")
            self.assertNotIn(client_ip, config.login_lockout)

        response = auth._record_failure(None, client_ip, "admin")

        self.assertEqual(response.status_code, 429)
        self.assertIn(client_ip, config.login_lockout)


class AdminLoginPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_login_page_renders_even_when_session_is_valid(self):
        request = Mock()

        with (
            patch("app.routes.pages._is_mobile", return_value=False),
            patch("app.routes.pages._check_auth", return_value=True),
            patch("app.routes.pages.render", return_value="login page"),
        ):
            response = await pages.login_page(request, session="valid-session")

        self.assertIsInstance(response, HTMLResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"login page")

    async def test_admin_mobile_login_page_renders_even_when_session_is_valid(self):
        request = Mock()

        with (
            patch("app.routes.pages._check_auth", return_value=True),
            patch("app.routes.pages.render", return_value="mobile login page"),
        ):
            response = await pages.mobile_login_page(request, session="valid-session")

        self.assertIsInstance(response, HTMLResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"mobile login page")


if __name__ == "__main__":
    unittest.main()
