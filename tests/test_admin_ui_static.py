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
        self.assertIn("standardModelsLoadPromise = standardModelsLoadPromise || loadStandardModels()", html)
        self.assertIn("mcpServersLoadPromise = mcpServersLoadPromise || loadMcpServers()", html)
        self.assertIn("loadApiKeys().catch(renderApiKeyLoadError)", html)
        self.assertNotIn(".then(() => loadApiKeys().catch(renderApiKeyLoadError))", html)
        self.assertIn("Failed to load API keys", html)
        self.assertNotIn('<span id="total-count">0</span>', html)

    def test_api_key_page_defers_large_picker_rendering_until_modal_opens(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        standard_loader = html[html.index("async function loadStandardModels()"):html.index("function isAutoModel")]
        add_modal = html[html.index("function showAddApiKey()"):html.index("function editApiKey")]
        edit_modal = html[html.index("function editApiKey(id)"):html.index("function closeApiKeyModal")]

        self.assertNotIn("renderStandardModelCheckboxes()", standard_loader)
        self.assertIn("prepareApiKeyPickers", html)
        self.assertIn("prepareApiKeyPickers", add_modal)
        self.assertIn("prepareApiKeyPickers", edit_modal)

    def test_api_key_list_route_batches_related_access_queries(self):
        source = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")
        list_body = source[source.index("async def list_api_keys"):source.index("@router.post(\"/keys\")")]

        self.assertIn("key_ids = [k.id for k in keys]", list_body)
        self.assertIn("ApiKeyModelAccess.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyTimeRule.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyMcpServer.api_key_id.in_(key_ids)", list_body)
        self.assertIn("ApiKeyTag.api_key_id.in_(key_ids)", list_body)

    def test_api_key_list_uses_payload_model_names_not_lazy_picker_cache(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "keys.py").read_text(encoding="utf-8")
        render_body = html[html.index("function renderApiKeys()"):html.index("function renderPagination()")]

        self.assertIn("allowed_model_names", render_body)
        self.assertNotIn("allowed_provider_model_names", render_body)
        self.assertNotIn('"allowed_provider_model_names"', route)
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

        self.assertIn("access_mode: 'model'", html)
        self.assertIn("validateApiKeyAccessSelection()", html)
        self.assertNotIn('id="access-mode-all"', html)
        self.assertIn("selectAllStandardModels", html)
        self.assertNotIn("selectAllProviderModels", html)
        self.assertNotIn("access-mode-provider-model", html)
        self.assertNotIn("provider-models-panel", html)
        self.assertIn("access_mode: Optional[str] = None", route)
        self.assertIn("_validate_access_payload", route)

    def test_edit_api_key_does_not_auto_select_all_models_when_no_bindings(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")
        edit_start = html.index("async function editApiKey(id)")
        edit_end = html.index("function closeApiKeyModal()", edit_start)
        edit_body = html[edit_start:edit_end]

        self.assertNotIn("selectedStandardModelIds = standardModels.map(model => model.id)", edit_body)
        self.assertNotIn("selectedModelIds", edit_body)
        self.assertIn("selectedStandardModelIds = [...(key.allowed_model_ids || [])]", edit_body)

    def test_api_key_model_picker_invalidates_cache_after_selection_changes(self):
        html = (ROOT / "web" / "templates" / "admin" / "api_keys.html").read_text(encoding="utf-8")

        standard_toggle = html[html.index("function toggleStandardModel"):html.index("function selectAllStandardModels")]
        bulk_controls = html[html.index("function selectAllStandardModels"):html.index("function updateSelectedCount")]
        prepare = html[html.index("function prepareApiKeyPickers"):html.index("function copyKey")]

        self.assertIn("standardModelPickerCacheKey = ''", standard_toggle)
        self.assertIn("renderStandardModelCheckboxes(true)", bulk_controls)
        self.assertIn("renderStandardModelCheckboxes(true)", prepare)
        self.assertNotIn("renderModelCheckboxes", prepare)

    def test_user_opencode_tab_shows_target_path_and_macos_hidden_folder_shortcuts(self):
        html = (ROOT / "web" / "templates" / "user" / "tab_opencode.html").read_text(encoding="utf-8")

        self.assertIn("copyOpencodeConfigDir", html)
        self.assertIn("downloadConfig", html)
        self.assertIn("downloaded file to this folder", html)
        self.assertIn("⌘", html)
        self.assertIn("Shift", html)
        self.assertIn("Cmd + Shift + .", html)
        self.assertIn("Cmd + Shift + G", html)

    def test_user_cost_card_downloads_billing_details_for_current_period(self):
        tab = (ROOT / "web" / "templates" / "user" / "tab_stats.html").read_text(encoding="utf-8")
        dashboard = (ROOT / "web" / "templates" / "user" / "dashboard.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "user.py").read_text(encoding="utf-8")

        self.assertIn("downloadBillingDetails()", tab)
        self.assertIn("function downloadBillingDetails", dashboard)
        self.assertIn("/user/api/billing-details.csv?period=", dashboard)
        self.assertIn("modelgate_billing_", route)
        self.assertIn("def _build_billing_detail_rows", route)

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

        self.assertIn("max-height: calc(100vh - 4rem)", html)
        self.assertIn("max-height: calc(100dvh - 4rem)", html)
        self.assertNotIn("max-h-[calc(100vh-1.5rem)]", html)
        self.assertNotIn(" h-[calc(100vh-1.5rem)]", html)
        self.assertIn("flex min-h-0 flex-1 flex-col overflow-hidden", html)
        self.assertIn("apikey-modal-body", html)
        self.assertIn("shrink-0 border-t", html)
        self.assertIn("md:grid-cols-2", html)
        self.assertIn("apikey-mcp-servers", html)
        self.assertIn("apikey-tags-container", html)

    def test_admin_modals_reserve_taskbar_safe_height(self):
        files = [
            "api_keys.html",
            "config.html",
            "mcp_servers.html",
            "documents.html",
            "reports.html",
            "request_logs.html",
            "users.html",
            "roles.html",
        ]

        for name in files:
            with self.subTest(template=name):
                html = (ROOT / "web" / "templates" / "admin" / name).read_text(encoding="utf-8")
                self.assertIn("calc(100dvh - 4rem)", html)
                self.assertNotIn("h-[90vh]", html)
                self.assertNotIn("max-h-[90vh]", html)

    def test_admin_form_modals_keep_actions_outside_scroll_body(self):
        config = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        mcp = (ROOT / "web" / "templates" / "admin" / "mcp_servers.html").read_text(encoding="utf-8")
        users = (ROOT / "web" / "templates" / "admin" / "users.html").read_text(encoding="utf-8")
        roles = (ROOT / "web" / "templates" / "admin" / "roles.html").read_text(encoding="utf-8")

        self.assertIn('id="provider-form" class="flex min-h-0 flex-1 flex-col overflow-hidden"', config)
        self.assertIn('id="model-form" class="flex min-h-0 flex-1 flex-col overflow-hidden"', config)
        self.assertIn('id="server-form" class="flex min-h-0 flex-1 flex-col overflow-hidden"', mcp)
        self.assertIn("border-t p-4 shrink-0", config)
        self.assertIn("border-t p-4 shrink-0", mcp)
        self.assertIn(".modal-actions", users)
        self.assertIn(".modal-actions", roles)

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
        self.assertIn(".routing-upstream-input { width: 100%; min-width: 12rem; }", html)
        self.assertIn(".routing-priority-input { width: 4rem; max-width: 100%; }", html)
        self.assertIn(".routing-busyness-select { width: 5.25rem; max-width: 100%; }", html)
        self.assertIn("class=\"routing-priority-input border rounded px-2 py-1.5 text-sm text-center\"", html)
        self.assertNotIn("class=\"w-20 border rounded px-2 py-1.5 text-sm text-center\"", html)
        self.assertNotIn("xl:grid-cols-[1.2fr_150px_1fr_120px_90px_110px_110px_110px_110px_120px_auto]", html)
        self.assertNotIn("xl:grid-cols-[1fr_120px_90px_95px_95px_95px_95px_95px_95px_100px_auto]", html)

    def test_model_routing_matrix_has_no_bulk_api_key_configuration(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "models.py").read_text(encoding="utf-8")

        self.assertNotIn('id="model-keys-modal"', html)
        self.assertNotIn("openModelKeys", html)
        self.assertNotIn("openProviderModelKeys", html)
        self.assertNotIn("配置 Key", html)
        self.assertNotIn("/models/{model_id}/api-keys", route)
        self.assertNotIn("ModelApiKeysUpdate", route)

    def test_model_routing_rules_can_scope_provider_keys(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        routing_route = (ROOT / "app" / "routes" / "routing.py").read_text(encoding="utf-8")
        provider_models_route = (ROOT / "app" / "routes" / "provider_models.py").read_text(encoding="utf-8")

        self.assertIn('id="model-rule-provider-keys"', html)
        self.assertIn("model-rule-edit-provider-keys", html)
        self.assertIn("selectedModelRuleKeyIds", html)
        self.assertIn("provider_key_ids", html)
        self.assertIn("provider_key_ids: list[int] = []", routing_route)
        self.assertIn("_valid_provider_key_ids", routing_route)
        self.assertIn('"provider_key_ids": rule.provider_key_ids or []', provider_models_route)
        self.assertIn('"provider_keys": provider_keys', provider_models_route)

    def test_provider_key_modal_has_no_rule_strategy_configuration(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        routing_route = (ROOT / "app" / "routes" / "routing.py").read_text(encoding="utf-8")
        provider_service = (ROOT / "app" / "services" / "provider.py").read_text(encoding="utf-8")

        self.assertNotIn('id="provider-key-strategy-drawer"', html)
        self.assertNotIn("openProviderKeyStrategy", html)
        self.assertNotIn("saveProviderKeyStrategy", html)
        self.assertNotIn("strategy_assignment", html)
        self.assertNotIn("routing_rule_count", html)
        self.assertNotIn('/keys/{key_id}/strategy', routing_route)
        self.assertNotIn("ProviderKeyStrategyAssignment", provider_service)
        self.assertNotIn("ProviderKeyRoutingRule", provider_service)

    def test_model_routing_matrix_shows_rule_key_scope_summary(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("function renderRouteRuleSummary", html)
        self.assertIn("<th>路由规则</th>", html)
        self.assertIn("renderRouteRuleSummary(route)", html)
        self.assertIn("配置规则", html)
        self.assertIn("openModelRoutingConfig(${route.model_id})", html)
        self.assertIn("全部 Key", html)
        self.assertIn("限定", html)

    def test_model_routing_drawer_has_clear_sections_and_strategy_cards(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("1. 供应商顺序", html)
        self.assertIn("2. 路由策略", html)
        self.assertIn("新增策略", html)
        self.assertIn("已配置策略", html)
        self.assertIn("function modelRuleConditionSummary", html)
        self.assertIn("function modelRuleKeyScopeSummary", html)
        self.assertIn("编辑策略", html)

    def test_model_routing_rule_context_fields_are_entered_in_k_tokens(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("上下文下限(k tokens)", html)
        self.assertIn("上下文上限(k tokens)", html)
        self.assertIn("function modelRuleKTokensValue", html)
        self.assertIn("function formatRuleContextK", html)
        self.assertIn("min_context_tokens: modelRuleKTokensValue('model-rule-min-context')", html)
        self.assertIn("max_context_tokens: modelRuleKTokensValue('model-rule-max-context')", html)
        self.assertIn("value=\"${formatRuleContextK(rule.min_context_tokens, false)}\"", html)
        self.assertIn("value=\"${formatRuleContextK(rule.max_context_tokens, false)}\"", html)
        self.assertIn("ctx <= ${formatRuleContextK(rule.max_context_tokens)}", html)

    def test_config_availability_status_uses_compact_label_with_tooltip(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")

        self.assertIn("function renderAvailabilityPill", html)
        self.assertIn("title=\"${escapeAttr(title || label)}\"", html)
        self.assertIn("renderRouteAvailability(route)", html)
        self.assertNotIn("const statusText = disabled ? (route.provider_disabled_reason || '供应商停用') : '供应商可用';", html)
        self.assertNotIn("${escapeHtml(statusText)}</span>", html)

    def test_model_billing_has_separate_config_tab(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        route = (ROOT / "app" / "routes" / "provider_models.py").read_text(encoding="utf-8")
        database = (ROOT / "app" / "core" / "database.py").read_text(encoding="utf-8")

        self.assertIn('data-config-tab="billing"', html)
        self.assertIn('id="config-tab-billing"', html)
        self.assertIn("loadModelPricing", html)
        self.assertIn("saveModelPricing", html)
        self.assertIn("input_price_cny_per_million", html)
        self.assertIn("default_cache_hit_ratio", html)
        self.assertIn("/provider-models/{pm_id}/pricing", route)
        self.assertIn("class ProviderModelPricingUpdate", route)
        self.assertIn("input_price_cny_per_million = Column", database)
        self.assertIn("pricing_tiers = Column(JSONB", database)

    def test_user_catalog_renders_price_badge(self):
        html = (ROOT / "web" / "templates" / "user" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("min_input_price", html)
        self.assertIn("价格未配置", html)
        self.assertIn("showPriceDetail", html)

    def test_user_price_detail_modal_exists(self):
        html = (ROOT / "web" / "templates" / "user" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('id="price-detail-modal"', html)
        self.assertIn("function showPriceDetail", html)
        self.assertIn("function closePriceDetail", html)

    def test_config_reorganized_tabs(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        self.assertIn('data-config-tab="provider-models"', html)
        self.assertIn('data-config-tab="pricing"', html)
        self.assertIn('id="config-tab-provider-models"', html)
        self.assertIn('id="config-tab-pricing"', html)
        self.assertIn('if (tab === \'provider-models\') loadProviderModelRoutes();', html)
        self.assertIn('if (tab === \'pricing\') loadModelPricing();', html)

    def test_pricing_overview_has_filters_and_actions(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(encoding="utf-8")
        self.assertIn('id="pricing-filter-provider"', html)
        self.assertIn('id="pricing-filter-model"', html)
        self.assertIn('openBatchPricingModal', html)
        self.assertIn('openCopyPricingModal', html)
        self.assertIn('syncPricingToSiblings', html)
        self.assertIn('exportPricingCsv', html)
        self.assertIn('toggleAllPricing', html)


if __name__ == "__main__":
    unittest.main()
