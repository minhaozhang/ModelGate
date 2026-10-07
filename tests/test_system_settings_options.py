"""系统设置新增项：UA 策略/透传、请求内容留存开关、OpenCode 供应商名称、供应商 URL 探测。"""

import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class UaModeTests(unittest.TestCase):
    def test_outbound_user_agent_defaults_to_override(self):
        import app.core.config as config

        with patch.dict(config.system_settings, {}, clear=True), patch.object(
            config, "OUTBOUND_USER_AGENT", "fixed-ua"
        ):
            self.assertEqual(config.outbound_user_agent("client-ua"), "fixed-ua")

    def test_outbound_user_agent_passthrough(self):
        import app.core.config as config

        with patch.dict(
            config.system_settings, {"proxy.ua_mode": "passthrough"}, clear=True
        ), patch.object(config, "OUTBOUND_USER_AGENT", "fixed-ua"):
            self.assertEqual(config.outbound_user_agent("client-ua"), "client-ua")
            # 客户端没带 UA 时回退固定 UA，避免上游收到空 UA
            self.assertEqual(config.outbound_user_agent(None), "fixed-ua")

    def test_openai_adapter_forwards_client_ua_only_in_passthrough(self):
        import app.core.config as config
        from app.services.proxy_runtime.adapters.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with patch.object(config, "OUTBOUND_USER_AGENT", "fixed-ua"):
            with patch.dict(config.system_settings, {}, clear=True):
                headers = adapter.build_headers(
                    {}, api_key="k", client_user_agent="curl/8"
                )
                self.assertEqual(headers["user-agent"], "fixed-ua")
            with patch.dict(
                config.system_settings, {"proxy.ua_mode": "passthrough"}, clear=True
            ):
                headers = adapter.build_headers(
                    {}, api_key="k", client_user_agent="curl/8"
                )
                self.assertEqual(headers["user-agent"], "curl/8")

    def test_proxy_pipeline_passes_client_ua(self):
        source = (ROOT / "app" / "services" / "proxy.py").read_text(encoding="utf-8")
        self.assertIn("client_user_agent=user_agent", source)
        builder = (
            ROOT / "app" / "services" / "proxy_runtime" / "request_builder.py"
        ).read_text(encoding="utf-8")
        self.assertIn("client_user_agent", builder)

    def test_system_config_api_exposes_ua_mode(self):
        source = (ROOT / "app" / "routes" / "system_config.py").read_text(encoding="utf-8")
        self.assertIn('"ua_mode"', source)
        self.assertIn('if "ua_mode" in body', source)
        # 回归：只有 payload 带 ua_override 时才允许改它，否则保存其它设置会清空 UA
        self.assertIn('if "ua_override" in body', source)
        html = (
            ROOT / "web" / "templates" / "admin" / "system_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="ua-mode-select"', html)
        self.assertIn('value="passthrough"', html)
        self.assertIn("ua_mode", html)


class SystemConfigConsolidationTests(unittest.TestCase):
    """单值设置合并进「常规设置」一张表，旧的单值 tab 面板移除。"""

    def test_single_value_settings_live_in_general_tab_table(self):
        html = (
            ROOT / "web" / "templates" / "admin" / "system_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="sys-tab-general"', html)
        # 合并进来的行级控件与保存函数
        for needle in (
            'id="ua-mode-select"',
            'id="ua-input"',
            'id="record-content-input"',
            'id="opencode-provider-id"',
            'id="opencode-provider-name"',
            'id="glm-model-input"',
            "sysSaveUaMode",
            "sysSaveUa(",
            "sysSaveContent",
            "sysSaveOpencode(",
            "sysSaveGlmModel",
        ):
            self.assertIn(needle, html)
        # 旧的单值 tab 面板不复存在
        for legacy in (
            'id="sys-tab-ua"',
            'id="sys-tab-content"',
            'id="sys-tab-opencode"',
            'id="sys-tab-glm"',
            "ua-mode-override",
            "ua-mode-passthrough",
        ):
            self.assertNotIn(legacy, html)
        # tab 注册表：general 在列，且旧的 ua/glm 不再注册
        self.assertIn("const SYS_TABS = ['general',", html)
        self.assertIn("'ips']", html)

    def test_row_level_save_uses_field_gated_put(self):
        """逐行保存依赖 PUT 的按字段 gating：每行只提交自己的字段。"""
        html = (
            ROOT / "web" / "templates" / "admin" / "system_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn("JSON.stringify({ ua_mode: uaMode })", html)
        self.assertIn("JSON.stringify({ ua_override: ua })", html)
        self.assertIn("JSON.stringify({ record_content: record })", html)
        self.assertIn(
            "JSON.stringify({ opencode_provider_id: pid, opencode_provider_name: pname })",
            html,
        )


class ContentRecordingTests(unittest.TestCase):
    def test_content_recording_enabled_defaults_true(self):
        import app.core.config as config

        with patch.dict(config.system_settings, {}, clear=True):
            self.assertTrue(config.content_recording_enabled())
        with patch.dict(
            config.system_settings, {"proxy.record_content": "false"}, clear=True
        ):
            self.assertFalse(config.content_recording_enabled())
        with patch.dict(
            config.system_settings, {"proxy.record_content": "true"}, clear=True
        ):
            self.assertTrue(config.content_recording_enabled())

    def test_logging_gates_request_and_response_content(self):
        source = (ROOT / "app" / "services" / "logging.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("config_module.content_recording_enabled()"), 3)
        self.assertIn("if not config_module.content_recording_enabled()", source)

    def test_system_config_api_exposes_content_toggle(self):
        source = (ROOT / "app" / "routes" / "system_config.py").read_text(encoding="utf-8")
        self.assertIn('"record_content"', source)
        self.assertIn('if "record_content" in body', source)
        html = (
            ROOT / "web" / "templates" / "admin" / "system_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn("record-content-input", html)
        self.assertIn("sysSaveContent", html)


class OpencodeIdentityTests(unittest.TestCase):
    def test_service_defaults_and_helpers(self):
        source = (
            ROOT / "app" / "services" / "system_config.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"opencode": {', source)
        self.assertIn('"provider_id": "modelgate"', source)
        self.assertIn("async def get_opencode_identity", source)
        self.assertIn("def valid_opencode_provider_id", source)

    def test_identity_reads_settings_snapshot_without_db(self):
        """身份读取走内存快照(启动加载 + save_setting 即时更新),请求路径不额外查库。"""
        import asyncio

        import app.core.config as config
        from app.services import system_config as sc

        with patch.dict(config.system_settings, {}, clear=True):
            self.assertEqual(
                asyncio.run(sc.get_opencode_identity()), ("modelgate", "ModelGate")
            )
        with patch.dict(
            config.system_settings,
            {"opencode.provider_id": "mygw", "opencode.provider_name": "My GW"},
            clear=True,
        ):
            self.assertEqual(
                asyncio.run(sc.get_opencode_identity()), ("mygw", "My GW")
            )

    def test_generated_config_uses_configured_identity(self):
        from app.routes.opencode import build_setup_markdown, provider_block

        config = {
            "provider": {
                "mygw": {
                    "name": "MyGW",
                    "npm": "@ai-sdk/openai-compatible",
                    "models": {"m1": {"name": "M1"}},
                }
            }
        }
        self.assertEqual(provider_block(config)[0], "mygw")
        md = build_setup_markdown(config)
        self.assertIn("provider.mygw", md)
        self.assertIn("`mygw.models`", md)
        self.assertNotIn("provider.modelgate", md)

    def test_setup_script_and_merge_use_placeholder(self):
        source = (ROOT / "app" / "routes" / "opencode.py").read_text(encoding="utf-8")
        self.assertIn("providers[pid] = pblock", source)
        self.assertIn("$resp.provider.__PROVIDER_ID__.models", source)
        self.assertIn("__PROVIDER_ID__", source)
        self.assertNotIn('providers["modelgate"]', source)
        # provider id/name 由路由层注入(避免 build_opencode_config 里跨事件循环查库)
        self.assertNotIn("await get_opencode_identity()", source.split("def build_setup_markdown")[0])
        self.assertIn("provider_id=provider_id", source)

    def test_system_config_ui_and_api(self):
        source = (ROOT / "app" / "routes" / "system_config.py").read_text(encoding="utf-8")
        self.assertIn('"opencode_provider_id"', source)
        self.assertIn("valid_opencode_provider_id", source)
        html = (
            ROOT / "web" / "templates" / "admin" / "system_config.html"
        ).read_text(encoding="utf-8")
        self.assertIn("opencode-provider-id", html)
        self.assertIn("sysSaveOpencode", html)


class ProviderProbeTests(unittest.TestCase):
    def test_probe_endpoint(self):
        source = (ROOT / "app" / "routes" / "providers.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/providers/probe")', source)
        self.assertIn("select(ProviderKey)", source)
        self.assertIn("httpx.AsyncClient(timeout=8.0)", source)
        self.assertIn("f\"{base_url}{path}\"", source)
        self.assertIn("provider.protocol", source)

    def test_probe_target_and_headers_follow_protocol(self):
        from app.routes.providers import _probe_headers, _probe_target

        self.assertEqual(_probe_target("https://x", "openai"), ("/models", False))
        self.assertEqual(_probe_target("https://x", "anthropic"), ("/v1/models", True))
        # 大小写/空白容错
        self.assertEqual(_probe_target("https://x", " Anthropic "), ("/v1/models", True))

        openai_headers = _probe_headers("sk-k", False)
        self.assertEqual(openai_headers["Authorization"], "Bearer sk-k")
        self.assertNotIn("x-api-key", openai_headers)

        anthropic_headers = _probe_headers("sk-k", True)
        self.assertEqual(anthropic_headers["x-api-key"], "sk-k")
        self.assertIn("anthropic-version", anthropic_headers)
        self.assertNotIn("Authorization", anthropic_headers)

        # 无 key 时不带鉴权头（新增供应商未保存前也能探测连通性）
        self.assertEqual(_probe_headers(None, True), {"Accept": "application/json"})

    def test_probe_button_in_provider_modal(self):
        html = (ROOT / "web" / "templates" / "admin" / "config.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("provider-probe-btn", html)
        self.assertIn("probeProviderUrl", html)
        self.assertIn("/admin/api/providers/probe", html)
        # 探测请求带上弹窗当前选中的协议
        self.assertIn("payload.protocol = proto", html)


if __name__ == "__main__":
    unittest.main()
