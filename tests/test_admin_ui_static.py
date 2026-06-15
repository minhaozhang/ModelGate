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

    def test_priority_dark_mode_templates_have_dark_overrides(self):
        public_query = (ROOT / "web" / "templates" / "public" / "query.html").read_text(encoding="utf-8")
        public_opencode = (ROOT / "web" / "templates" / "public" / "opencode.html").read_text(encoding="utf-8")
        nav = (ROOT / "web" / "templates" / "components" / "nav.html").read_text(encoding="utf-8")
        scheduler_tasks = (ROOT / "web" / "templates" / "admin" / "scheduler_tasks_tab.html").read_text(encoding="utf-8")
        scheduler_logs = (ROOT / "web" / "templates" / "admin" / "scheduler_logs_tab.html").read_text(encoding="utf-8")

        self.assertIn("body.theme-dark", public_query)
        self.assertIn('<body class="theme-dark', public_query)
        self.assertIn("dark-surface", public_query)
        self.assertIn("dark-row", public_query)
        self.assertIn("dark-status-success", public_query)

        self.assertIn("body.theme-dark", public_opencode)
        self.assertIn('<body class="theme-dark', public_opencode)
        self.assertIn("dark-surface", public_opencode)
        self.assertIn("dark-code", public_opencode)
        self.assertIn("dark-row", public_opencode)

        self.assertIn("dark:bg-slate-900", nav)
        self.assertIn("dark:text-slate-100", nav)
        self.assertIn("dark:border-slate-800", nav)

        self.assertIn("dark:bg-slate-900", scheduler_tasks)
        self.assertIn("dark:border-slate-800", scheduler_tasks)
        self.assertIn("dark:text-slate-100", scheduler_tasks)
        self.assertIn("dark:bg-amber-500/15", scheduler_tasks)
        self.assertIn("dark:bg-red-500/10", scheduler_tasks)

        self.assertIn("dark:bg-slate-900", scheduler_logs)
        self.assertIn("dark:border-slate-800", scheduler_logs)
        self.assertIn("dark:text-slate-100", scheduler_logs)
        self.assertIn("dark:bg-slate-900", scheduler_logs)

    def test_api_key_form_exposes_email_and_expiry_fields(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")

        self.assertIn('id="apikey-email"', html)
        self.assertIn('id="apikey-expires-at"', html)
        self.assertIn("getDefaultApiKeyExpiry", html)
        self.assertIn("email: document.getElementById('apikey-email').value.trim()", html)
        self.assertIn("expires_at: localDateTimeToIso", html)
        self.assertIn("formatExpiry", html)
        self.assertIn("isApiKeyExpired", html)
        self.assertIn("email: Optional[str] = None", route)
        self.assertIn("expires_at: Optional[datetime] = None", route)

    def test_api_key_modal_does_not_close_from_backdrop_click(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        mcp = (ROOT / "web" / "templates" / "admin" / "mcp_servers.html").read_text(encoding="utf-8")

        self.assertIn("apikey-modal-card", html)
        self.assertNotIn("if (e.target.id === 'apikey-modal') closeApiKeyModal();", html)
        self.assertNotIn("if (e.target.id === 'timerule-modal') closeTimeRuleModal();", html)
        self.assertNotIn("e.target.id === 'manual-copy-modal'", html)
        self.assertNotIn("if (e.target.id === 'server-modal') closeServerModal();", mcp)

    def test_api_key_model_access_requires_explicit_all_or_non_empty_selection(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")

        self.assertIn("access_mode: selectedAccessMode", html)
        self.assertIn("validateApiKeyAccessSelection()", html)
        self.assertNotIn('id="access-mode-all"', html)
        self.assertIn("selectAllStandardModels", html)
        self.assertIn("selectAllProviderModels", html)
        self.assertIn("access_mode: Optional[str] = None", route)
        self.assertIn("_validate_access_payload", route)

    def test_user_opencode_tab_shows_target_path_and_macos_hidden_folder_shortcuts(self):
        html = (ROOT / "web" / "templates" / "user" / "tab_opencode.html").read_text(encoding="utf-8")

        self.assertIn("copyOpencodeConfigDir", html)
        self.assertIn("downloadConfig", html)
        self.assertIn("downloaded file to this folder", html)
        self.assertIn("⌘", html)
        self.assertIn("Shift", html)
        self.assertIn("Cmd + Shift + .", html)
        self.assertIn("Cmd + Shift + G", html)

    def test_auto_model_picker_uses_compact_modal_not_tall_multiselect(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn('id="auto-model-summary"', html)
        self.assertIn('id="auto-model-picker-modal"', html)
        self.assertIn("openAutoModelPicker", html)
        self.assertIn("confirmAutoModelPicker", html)
        self.assertIn("autoModelDraftIds", html)
        self.assertNotIn('id="auto-model-ids" multiple', html)

    def test_api_key_standard_model_picker_marks_virtual_models(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        self.assertIn("model.is_virtual", html)
        self.assertIn("虚拟", html)

    def test_model_routing_matrix_uses_compact_responsive_layout(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("routing-table", html)
        self.assertIn("routing-rule-editor", html)
        self.assertNotIn("xl:grid-cols-[1.2fr_150px_1fr_120px_90px_110px_110px_110px_110px_120px_auto]", html)
        self.assertNotIn("xl:grid-cols-[1fr_120px_90px_95px_95px_95px_95px_95px_95px_100px_auto]", html)


if __name__ == "__main__":
    unittest.main()
