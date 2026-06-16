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
        self.assertIn("providerModelsLoadPromise = providerModelsLoadPromise || loadProviderModels()", html)
        self.assertIn("standardModelsLoadPromise = standardModelsLoadPromise || loadStandardModels()", html)
        self.assertIn("mcpServersLoadPromise = mcpServersLoadPromise || loadMcpServers()", html)
        self.assertIn("loadApiKeys().catch(renderApiKeyLoadError)", html)
        self.assertNotIn(".then(() => loadApiKeys().catch(renderApiKeyLoadError))", html)
        self.assertIn("Failed to load API keys", html)
        self.assertNotIn('<span id="total-count">0</span>', html)

    def test_api_key_page_defers_large_picker_rendering_until_modal_opens(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        provider_loader = html[html.index("async function loadProviderModels()"):html.index("async function loadStandardModels()")]
        standard_loader = html[html.index("async function loadStandardModels()"):html.index("function isAutoModel")]
        add_modal = html[html.index("function showAddApiKey()"):html.index("function editApiKey")]
        edit_modal = html[html.index("function editApiKey(id)"):html.index("function closeApiKeyModal")]

        self.assertNotIn("renderModelCheckboxes()", provider_loader)
        self.assertNotIn("renderStandardModelCheckboxes()", standard_loader)
        self.assertIn("prepareApiKeyPickers", html)
        self.assertIn("prepareApiKeyPickers", add_modal)
        self.assertIn("prepareApiKeyPickers", edit_modal)

    def test_api_key_list_route_batches_related_access_queries(self):
        source = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")
        list_body = source[source.index("async def list_api_keys"):source.index("@router.post(\"/keys\")")]

        self.assertIn("key_ids = [k.id for k in keys]", list_body)
        self.assertIn("ApiKeyModel.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyModelAccess.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyTimeRule.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyMcpServer.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyTag.api_key_id.in_(key_ids)", list_body)

    def test_api_key_list_uses_payload_model_names_not_lazy_picker_cache(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")
        render_body = html[html.index("function renderApiKeys()"):html.index("function renderPagination()")]

        self.assertIn("allowed_model_names", render_body)
        self.assertIn("allowed_provider_model_names", render_body)
        self.assertIn('"allowed_provider_model_names"', route)
        self.assertIn('"allowed_model_names"', route)

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

    def test_api_key_create_strips_timezone_from_expiry(self):
        route = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")
        create_body = route[route.index("async def create_api_key"):route.index("@router.put(\"/keys/{key_id}\")")]

        self.assertIn("data.expires_at.replace(tzinfo=None)", create_body)
        self.assertIn("data.expires_at.tzinfo", create_body)

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

    def test_saving_auto_model_refreshes_model_list(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        save_start = html.index("async function saveAutoModelConfig()")
        save_end = html.index("function applyModelFilters()", save_start)
        save_body = html[save_start:save_end]

        self.assertIn("await loadModels()", save_body)

    def test_auto_virtual_model_delete_button_is_hidden(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        table_start = html.index("function renderModelTable(models)")
        table_end = html.index("async function loadProviderModelRoutes()", table_start)
        table_body = html[table_start:table_end]

        self.assertIn("isProtectedAutoModel", html)
        self.assertIn("const canDeleteModel = !isProtectedAutoModel(m)", table_body)
        self.assertIn("${canDeleteModel ? `", table_body)
        self.assertIn("deleteModel(${m.id})", table_body)

    def test_api_key_standard_model_picker_marks_virtual_models(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        self.assertIn("model.is_virtual", html)
        self.assertIn("虚拟", html)

    def test_api_key_standard_model_picker_prioritizes_auto_model(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        self.assertIn("isAutoModel", html)
        self.assertIn("auto-model-option", html)
        self.assertIn("Auto 路由", html)

    def test_api_key_modal_is_scrollable_with_fixed_actions_and_horizontal_sections(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        self.assertIn("max-h-[92vh]", html)
        self.assertIn("apikey-modal-body", html)
        self.assertIn("shrink-0 border-t", html)
        self.assertIn("md:grid-cols-2", html)
        self.assertIn("apikey-mcp-servers", html)
        self.assertIn("apikey-tags-container", html)

    def test_admin_home_websocket_unauthorized_redirects_and_stops_reconnect(self):
        home = (ROOT / "web" / "templates" / "admin" / "home.html").read_text(encoding="utf-8")
        mobile = (ROOT / "web" / "templates" / "admin" / "mobile_home.html").read_text(encoding="utf-8")

        for html, login_path in ((home, "/admin/login"), (mobile, "/admin/m/login")):
            self.assertIn("handleAdminUnauthorized", html)
            self.assertIn("event.code === 4401", html)
            self.assertIn("adminAuthRedirecting", html)
            self.assertIn(f"`${{APP_BASE_PATH}}{login_path}`", html)

    def test_model_routing_matrix_uses_compact_responsive_layout(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("routing-table", html)
        self.assertIn("routing-rule-editor", html)
        self.assertNotIn("xl:grid-cols-[1.2fr_150px_1fr_120px_90px_110px_110px_110px_110px_120px_auto]", html)
        self.assertNotIn("xl:grid-cols-[1fr_120px_90px_95px_95px_95px_95px_95px_95px_100px_auto]", html)


if __name__ == "__main__":
    unittest.main()
