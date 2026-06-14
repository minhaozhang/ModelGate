import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminUiStaticTests(unittest.TestCase):
    def test_config_templates_tab_is_registered(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn('data-config-tab="templates"', html)
        self.assertIn("'templates'", html)
        self.assertIn("if (tab === 'templates') loadStrategyTemplates();", html)

    def test_nav_logout_is_component_owned_and_not_clipped(self):
        html = (ROOT / "web" / "templates" / "components" / "nav.html").read_text(encoding="utf-8")

        self.assertIn("height: 100vh; display: flex; flex-direction: column;", html)
        self.assertIn("flex: 1 1 auto; min-height: 0; overflow-y: auto;", html)
        self.assertIn("onclick=\"modelGateLogout()\"", html)
        self.assertIn("window.modelGateLogout = async function()", html)

    def test_api_key_list_loads_independently_from_model_filters(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        self.assertIn("loadApiKeys().catch", html)
        self.assertIn("Promise.allSettled([loadProviderModels(), loadStandardModels(), loadMcpServers()])", html)
        self.assertIn("Failed to load API keys", html)
        self.assertNotIn('<span id="total-count">0</span>', html)

    def test_change_password_uses_defined_sqlalchemy_update(self):
        source = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")

        self.assertIn("from sqlalchemy import update", source)
        self.assertNotIn("sql_update(User)", source)


if __name__ == "__main__":
    unittest.main()
