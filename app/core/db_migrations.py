"""Startup schema migrations and seed data.

Every statement is idempotent and runs on each boot inside one transaction.
Grouped by domain; init_db() calls them in dependency-safe order.
"""

import app.core.db_models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.db_engine import Base, engine
from sqlalchemy import text

REQUEST_LOG_TABLES = ("request_logs", "request_logs_history")


async def migrate_request_logs(conn) -> None:
    for table_name in REQUEST_LOG_TABLES:
        for column_sql in (
            "request_context_tokens INTEGER",
            "upstream_status_code INTEGER",
            "downstream_status_code INTEGER",
            "client_ip VARCHAR(64)",
            "user_agent VARCHAR(1024)",
            "inbound_protocol VARCHAR(20)",
            "error TEXT",
            "intent VARCHAR(20)",
            "requested_model VARCHAR(100)",
            "actual_model VARCHAR(100)",
            "provider_key_id INTEGER",
            "provider_key_label VARCHAR(50)",
        ):
            await conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_sql}")
            )
        await conn.execute(
            text(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN IF NOT EXISTS routing_decision JSONB"
            )
        )
    await conn.execute(
        text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS archive_month VARCHAR(7)")
    )
    await conn.execute(
        text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP DEFAULT now()")
    )
    await conn.execute(
        text("UPDATE request_logs_history SET archive_month = to_char(created_at, 'YYYY-MM') WHERE archive_month IS NULL")
    )

    # request_logs_all: live + archived union view.
    columns = (
        "id, api_key_id, provider_id, model, response, tokens, latency_ms, "
        "request_context_tokens, status, upstream_status_code, downstream_status_code, client_ip, user_agent, "
        "inbound_protocol, error, intent, requested_model, actual_model, provider_key_id, provider_key_label, routing_decision, created_at, updated_at"
    )
    await conn.execute(text("DROP VIEW IF EXISTS request_logs_all"))
    await conn.execute(
        text(
            "CREATE VIEW request_logs_all AS "
            f"SELECT {columns} FROM request_logs "
            "UNION ALL "
            f"SELECT {columns} FROM request_logs_history"
        )
    )

    # Redundant/dead indexes (see git history for scan evidence).
    await conn.execute(text("DROP INDEX IF EXISTS uq_request_logs_history_id"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_request_logs_created_at"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_request_logs_history_created_at"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_request_logs_history_provider_id"))

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS request_contents ("
            "id SERIAL PRIMARY KEY, "
            "log_id INTEGER NOT NULL REFERENCES request_logs(id) ON DELETE CASCADE, "
            "request_messages JSONB, "
            "response_content TEXT, "
            "response_tool_calls JSONB, "
            "response_thinking TEXT, "
            "response_raw JSONB, "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(text("DROP INDEX IF EXISTS idx_request_contents_log_id"))


async def migrate_daily_stats(conn) -> None:
    for table_name in (
        "provider_daily_stats",
        "api_key_daily_stats",
        "api_key_model_daily_stats",
        "model_daily_stats",
    ):
        await conn.execute(
            text(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN IF NOT EXISTS rate_limited INTEGER DEFAULT 0"
            )
        )


async def migrate_api_keys(conn) -> None:
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP"))
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS email VARCHAR(255)"))
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP"))
    await conn.execute(
        text("UPDATE api_keys SET expires_at = now() + interval '1 year' WHERE expires_at IS NULL")
    )
    await conn.execute(
        text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS bypass_busyness BOOLEAN DEFAULT FALSE")
    )
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS preferred_tags TEXT"))

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS api_key_time_rules ("
            "id SERIAL PRIMARY KEY, "
            "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
            "rule_type VARCHAR(20) NOT NULL, "
            "allowed BOOLEAN DEFAULT TRUE, "
            "start_time TIME, "
            "end_time TIME, "
            "start_date DATE, "
            "end_date DATE, "
            "weekdays VARCHAR(20), "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_api_key_time_rules_key "
            "ON api_key_time_rules (api_key_id)"
        )
    )

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS api_key_model_access ("
            "id SERIAL PRIMARY KEY, "
            "api_key_id INTEGER NOT NULL REFERENCES api_keys(id), "
            "model_id INTEGER NOT NULL REFERENCES models(id), "
            "UNIQUE(api_key_id, model_id)"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_api_key_model_access_api_key_id "
            "ON api_key_model_access (api_key_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_api_key_model_access_model_id "
            "ON api_key_model_access (model_id)"
        )
    )


async def migrate_providers_and_keys(conn) -> None:
    await conn.execute(
        text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(255)")
    )
    await conn.execute(
        text(
            "ALTER TABLE providers ADD COLUMN IF NOT EXISTS protocol VARCHAR(20) DEFAULT 'openai'"
        )
    )
    await conn.execute(text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP"))
    await conn.execute(text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP"))
    await conn.execute(text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP"))
    await conn.execute(text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP"))
    await conn.execute(
        text("UPDATE providers SET protocol = 'openai' WHERE protocol IS NULL OR protocol = ''")
    )
    await conn.execute(
        text("ALTER TABLE providers DROP COLUMN IF EXISTS max_concurrent")
    )

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_keys ("
            "id SERIAL PRIMARY KEY, "
            "provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE, "
            "api_key VARCHAR(255) NOT NULL, "
            "label VARCHAR(50), "
            "max_concurrent INTEGER, "
            "is_active BOOLEAN DEFAULT TRUE, "
            "disabled_reason VARCHAR(255), "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW(), "
            "UNIQUE (provider_id, api_key)"
            ")"
        )
    )
    await conn.execute(
        text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS max_concurrent INTEGER")
    )
    await conn.execute(
        text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0")
    )
    await conn.execute(
        text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS cost_role VARCHAR(40) DEFAULT 'standard'")
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_provider_keys_provider ON provider_keys (provider_id)"
        )
    )

    # Legacy single-key column -> provider_keys row, only for providers that
    # have no key rows yet (first migration); never recreates deleted keys.
    await conn.execute(
        text(
            "INSERT INTO provider_keys (provider_id, api_key, label, is_active) "
            "SELECT id, api_key, 'default', TRUE "
            "FROM providers "
            "WHERE api_key IS NOT NULL AND api_key != '' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM provider_keys pk WHERE pk.provider_id = providers.id"
            ")"
        )
    )

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_key_strategy_templates ("
            "id SERIAL PRIMARY KEY, "
            "name VARCHAR(100) NOT NULL, "
            "template_key VARCHAR(80) NOT NULL UNIQUE, "
            "description TEXT, "
            "is_builtin BOOLEAN DEFAULT FALSE, "
            "is_active BOOLEAN DEFAULT TRUE, "
            "config_schema JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "rule_blueprint JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_key_strategy_templates_key "
            "ON provider_key_strategy_templates (template_key)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_key_strategy_assignments ("
            "id SERIAL PRIMARY KEY, "
            "provider_key_id INTEGER NOT NULL REFERENCES provider_keys(id) ON DELETE CASCADE, "
            "template_id INTEGER NOT NULL REFERENCES provider_key_strategy_templates(id), "
            "enabled BOOLEAN DEFAULT TRUE, "
            "params JSONB NOT NULL DEFAULT '{}'::jsonb, "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_provider_key_strategy_assignments_key "
            "ON provider_key_strategy_assignments (provider_key_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_key_routing_rules ("
            "id SERIAL PRIMARY KEY, "
            "provider_key_id INTEGER NOT NULL REFERENCES provider_keys(id) ON DELETE CASCADE, "
            "template_assignment_id INTEGER REFERENCES provider_key_strategy_assignments(id) ON DELETE CASCADE, "
            "name VARCHAR(100), "
            "rule_type VARCHAR(30) NOT NULL DEFAULT 'custom', "
            "enabled BOOLEAN DEFAULT TRUE, "
            "priority INTEGER DEFAULT 0, "
            "start_time TIME, "
            "end_time TIME, "
            "start_date DATE, "
            "end_date DATE, "
            "weekdays VARCHAR(20), "
            "min_context_tokens INTEGER, "
            "max_context_tokens INTEGER, "
            "action VARCHAR(20) NOT NULL DEFAULT 'prefer', "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_provider_key_routing_rules_key "
            "ON provider_key_routing_rules (provider_key_id)"
        )
    )
    await conn.execute(
        text(
            "INSERT INTO provider_key_strategy_templates "
            "(name, template_key, description, is_builtin, config_schema, rule_blueprint) "
            "VALUES "
            "('始终可用', 'always_available', 'Key 总是进入候选池，按 priority 和 health 排序。', TRUE, "
            "'{\"fields\": []}'::jsonb, "
            "'{\"rules\": []}'::jsonb), "
            "('指定时间段可用', 'time_window', '只在指定时间段内允许使用。', TRUE, "
            "'{\"fields\": [{\"key\":\"start_time\",\"type\":\"time\",\"label\":\"开放开始\"},{\"key\":\"end_time\",\"type\":\"time\",\"label\":\"开放结束\"}]}'::jsonb, "
            "'{\"rules\": [{\"action\":\"allow\",\"start_time\":\"${start_time}\",\"end_time\":\"${end_time}\"}]}'::jsonb), "
            "('小上下文优先', 'small_context_prefer', '小上下文请求命中时提高排序。', TRUE, "
            "'{\"fields\": [{\"key\":\"max_context_tokens\",\"type\":\"number\",\"label\":\"上下文上限\"},{\"key\":\"priority\",\"type\":\"number\",\"label\":\"命中加权\"}]}'::jsonb, "
            "'{\"rules\": [{\"action\":\"prefer\",\"max_context_tokens\":\"${max_context_tokens}\",\"priority\":\"${priority}\"}]}'::jsonb), "
            "('高峰期分流', 'peak_offload', '在高峰时间段和上下文限制内提高排序。', TRUE, "
            "'{\"fields\": [{\"key\":\"start_time\",\"type\":\"time\",\"label\":\"开始\"},{\"key\":\"end_time\",\"type\":\"time\",\"label\":\"结束\"},{\"key\":\"max_context_tokens\",\"type\":\"number\",\"label\":\"上下文上限\"},{\"key\":\"priority\",\"type\":\"number\",\"label\":\"命中加权\"}]}'::jsonb, "
            "'{\"rules\": [{\"action\":\"prefer\",\"start_time\":\"${start_time}\",\"end_time\":\"${end_time}\",\"max_context_tokens\":\"${max_context_tokens}\",\"priority\":\"${priority}\"}]}'::jsonb), "
            "('主 Key 不可用时备用', 'primary_unavailable_fallback', '主 Key 停用、health 不可用或并发耗尽时作为备用候选。', TRUE, "
            "'{\"fields\": [{\"key\":\"priority\",\"type\":\"number\",\"label\":\"备用加权\"}]}'::jsonb, "
            "'{\"rules\": [{\"action\":\"standby\",\"priority\":\"${priority}\"}]}'::jsonb), "
            "('按量计费 standby', 'metered_standby', '默认不开放，仅在高峰或主 Key 不可用时参与。', TRUE, "
            "'{\"fields\": [{\"key\":\"start_time\",\"type\":\"time\",\"label\":\"开放开始\"},{\"key\":\"end_time\",\"type\":\"time\",\"label\":\"开放结束\"},{\"key\":\"max_context_tokens\",\"type\":\"number\",\"label\":\"上下文上限\"},{\"key\":\"priority\",\"type\":\"number\",\"label\":\"命中加权\"}]}'::jsonb, "
            "'{\"rules\": [{\"action\":\"standby\",\"start_time\":\"${start_time}\",\"end_time\":\"${end_time}\",\"max_context_tokens\":\"${max_context_tokens}\",\"priority\":\"${priority}\"}]}'::jsonb) "
            "ON CONFLICT (template_key) DO UPDATE SET "
            "name = EXCLUDED.name, "
            "description = EXCLUDED.description, "
            "is_builtin = TRUE, "
            "is_active = TRUE, "
            "config_schema = EXCLUDED.config_schema, "
            "rule_blueprint = EXCLUDED.rule_blueprint, "
            "updated_at = NOW()"
        )
    )


async def migrate_provider_models(conn) -> None:
    await conn.execute(
        text("ALTER TABLE provider_models DROP COLUMN IF EXISTS max_concurrent")
    )
    for column_sql in (
        "alias VARCHAR(100)",
        "max_busyness_level INTEGER",
        "upstream_model_name VARCHAR(100)",
        "priority INTEGER DEFAULT 0",
        "input_price_cny_per_million FLOAT",
        "output_price_cny_per_million FLOAT",
        "cached_input_price_cny_per_million FLOAT",
        "default_cache_hit_ratio FLOAT DEFAULT 0",
        "pricing_tiers JSONB",
    ):
        await conn.execute(
            text(f"ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS {column_sql}")
        )
    await conn.execute(
        text(
            "UPDATE provider_models "
            "SET upstream_model_name = model_name_override "
            "WHERE upstream_model_name IS NULL "
            "AND model_name_override IS NOT NULL"
        )
    )

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_model_routing_rules ("
            "id SERIAL PRIMARY KEY, "
            "provider_model_id INTEGER NOT NULL REFERENCES provider_models(id) ON DELETE CASCADE, "
            "name VARCHAR(100), "
            "rule_type VARCHAR(30) NOT NULL DEFAULT 'custom', "
            "enabled BOOLEAN DEFAULT TRUE, "
            "priority INTEGER DEFAULT 0, "
            "start_time TIME, "
            "end_time TIME, "
            "start_date DATE, "
            "end_date DATE, "
            "weekdays VARCHAR(20), "
            "min_context_tokens INTEGER, "
            "max_context_tokens INTEGER, "
            "provider_key_ids JSONB, "
            "action VARCHAR(20) NOT NULL DEFAULT 'prefer', "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE provider_model_routing_rules "
            "ADD COLUMN IF NOT EXISTS provider_key_ids JSONB"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_provider_model_routing_rules_pm "
            "ON provider_model_routing_rules (provider_model_id)"
        )
    )


async def migrate_models(conn) -> None:
    for column_sql in (
        "thinking_enabled BOOLEAN DEFAULT TRUE",
        "thinking_budget INTEGER DEFAULT 8192",
        "estimated_price FLOAT DEFAULT 0",
        "is_virtual BOOLEAN DEFAULT FALSE",
        "reasoning_effort TEXT",
        "tags TEXT",
    ):
        await conn.execute(
            text(f"ALTER TABLE models ADD COLUMN IF NOT EXISTS {column_sql}")
        )


async def migrate_weixin(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE weixin_accounts "
            "ADD COLUMN IF NOT EXISTS api_key_id INTEGER REFERENCES api_keys(id)"
        )
    )


async def migrate_documents(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS file_object_name VARCHAR(500)"
        )
    )
    await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_type VARCHAR(20)"))
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS document_files ("
            "id SERIAL PRIMARY KEY, "
            "document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, "
            "filename VARCHAR(255) NOT NULL, "
            "object_name VARCHAR(500) NOT NULL, "
            "file_type VARCHAR(20) NOT NULL, "
            "file_size INTEGER DEFAULT 0, "
            "content_type VARCHAR(100), "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_document_files_doc_id "
            "ON document_files (document_id)"
        )
    )


async def migrate_analysis(conn) -> None:
    for column_sql in (
        "progress VARCHAR(200)",
        "template_id VARCHAR(100)",
        "template_version VARCHAR(50)",
        "params_json JSONB",
    ):
        await conn.execute(
            text(f"ALTER TABLE analysis_records ADD COLUMN IF NOT EXISTS {column_sql}")
        )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS analysis_subtasks ("
            "id SERIAL PRIMARY KEY, "
            "analysis_record_id INTEGER NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE, "
            "step_key VARCHAR(100) NOT NULL, "
            "step_label VARCHAR(150) NOT NULL, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "sort_order INTEGER DEFAULT 0, "
            "attempt_count INTEGER DEFAULT 0, "
            "max_attempts INTEGER DEFAULT 1, "
            "output JSONB, "
            "error TEXT, "
            "started_at TIMESTAMP, "
            "finished_at TIMESTAMP, "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_subtasks_record_step "
            "ON analysis_subtasks (analysis_record_id, step_key)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_analysis_subtasks_status "
            "ON analysis_subtasks (status)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS analysis_artifacts ("
            "id SERIAL PRIMARY KEY, "
            "analysis_record_id INTEGER NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE, "
            "subtask_id INTEGER REFERENCES analysis_subtasks(id) ON DELETE SET NULL, "
            "artifact_key VARCHAR(100) NOT NULL, "
            "artifact_type VARCHAR(50) NOT NULL, "
            "title VARCHAR(150), "
            "path TEXT, "
            "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
            "meta JSONB, "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_artifacts_record_key "
            "ON analysis_artifacts (analysis_record_id, artifact_key)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_analysis_artifacts_status "
            "ON analysis_artifacts (status)"
        )
    )
    await conn.execute(text("DROP INDEX IF EXISTS idx_analysis_records_status"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_analysis_records_expires_at"))


async def migrate_mcp(conn) -> None:
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS mcp_servers ("
            "id SERIAL PRIMARY KEY, "
            "name VARCHAR(100) NOT NULL, "
            "url VARCHAR(500) NOT NULL, "
            "auth_type VARCHAR(20) DEFAULT 'none', "
            "auth_token TEXT, "
            "auth_header VARCHAR(100) DEFAULT 'Authorization', "
            "is_active BOOLEAN DEFAULT TRUE, "
            "tool_prefix VARCHAR(50), "
            "last_sync_at TIMESTAMP, "
            "last_sync_error TEXT, "
            "created_at TIMESTAMP DEFAULT NOW(), "
            "updated_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(text("ALTER TABLE mcp_servers DROP COLUMN IF EXISTS api_key_id"))
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS api_key_mcp_servers ("
            "id SERIAL PRIMARY KEY, "
            "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
            "mcp_server_id INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE, "
            "UNIQUE (api_key_id, mcp_server_id)"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ak_mcp_unique "
            "ON api_key_mcp_servers (api_key_id, mcp_server_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS mcp_call_logs ("
            "id SERIAL PRIMARY KEY, "
            "api_key_id INTEGER REFERENCES api_keys(id), "
            "mcp_server_id INTEGER REFERENCES mcp_servers(id), "
            "tool_name VARCHAR(200) NOT NULL, "
            "arguments JSONB, "
            "result TEXT, "
            "is_error BOOLEAN DEFAULT FALSE, "
            "latency_ms FLOAT, "
            "client_ip VARCHAR(64), "
            "user_agent VARCHAR(1024), "
            "error TEXT, "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_created_at "
            "ON mcp_call_logs (created_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_server_id "
            "ON mcp_call_logs (mcp_server_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_tool_name "
            "ON mcp_call_logs (tool_name)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS mcp_call_daily_stats ("
            "id SERIAL PRIMARY KEY, "
            "mcp_server_id INTEGER NOT NULL REFERENCES mcp_servers(id), "
            "date VARCHAR(10) NOT NULL, "
            "hour INTEGER, "
            "calls INTEGER DEFAULT 0, "
            "errors INTEGER DEFAULT 0, "
            "avg_latency_ms FLOAT"
            ")"
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_mcp_stats_date ON mcp_call_daily_stats (date)")
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_stats_unique "
            "ON mcp_call_daily_stats (mcp_server_id, date, hour)"
        )
    )


async def migrate_audit_logs(conn) -> None:
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS audit_logs ("
            "id SERIAL PRIMARY KEY, "
            "user_id INTEGER, "
            "username VARCHAR(50), "
            "action VARCHAR(20) NOT NULL, "
            "resource VARCHAR(50) NOT NULL, "
            "resource_id VARCHAR(100), "
            "detail TEXT, "
            "request_body JSONB, "
            "client_ip VARCHAR(64), "
            "user_agent VARCHAR(1024), "
            "status_code INTEGER, "
            "created_at TIMESTAMP DEFAULT NOW()"
            ")"
        )
    )
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_user_id"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_resource"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_action"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at)"
        )
    )


async def migrate_scheduler(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_task_logs_task"))


def default_rbac_permissions() -> list[dict]:
    page_codes = [
        ("page.api_keys", "API Key 页面", "api_keys"),
        ("page.documents", "文档页面", "documents"),
        ("page.logs.requests", "请求日志页面", "logs"),
        ("page.mcp_servers", "MCP 服务器页面", "mcp_servers"),
        ("page.models", "标准模型页面", "models"),
        ("page.provider_models", "供应商模型页面", "provider_models"),
        ("page.providers", "供应商页面", "providers"),
        ("page.roles", "角色权限页面", "roles"),
        ("page.stats", "统计监控页面", "stats"),
        ("page.system.config", "系统配置页面", "system_config"),
        ("page.system.scheduler", "定时任务页面", "scheduler"),
        ("page.users", "用户管理页面", "users"),
    ]
    action_codes = [
        ("api_key.create", "创建 API Key", "api_key", "create"),
        ("api_key.update", "更新 API Key", "api_key", "update"),
        ("api_key.delete", "删除 API Key", "api_key", "delete"),
        ("api_key.add_time_rule", "新增 API Key 时间规则", "api_key", "create"),
        ("api_key.update_time_rule", "更新 API Key 时间规则", "api_key", "update"),
        ("api_key.delete_time_rule", "删除 API Key 时间规则", "api_key", "delete"),
        ("document.create", "创建文档", "document", "create"),
        ("document.upload", "上传文档", "document", "upload"),
        ("document.update", "更新文档", "document", "update"),
        ("document.delete", "删除文档", "document", "delete"),
        ("document.delete_file", "删除文档文件", "document", "delete"),
        ("log.create_report", "生成日志报告", "log", "create"),
        ("mcp_server.create", "创建 MCP 服务器", "mcp_server", "create"),
        ("mcp_server.update", "更新 MCP 服务器", "mcp_server", "update"),
        ("mcp_server.delete", "删除 MCP 服务器", "mcp_server", "delete"),
        ("mcp_server.sync", "同步 MCP 服务器", "mcp_server", "sync"),
        ("menu.create", "创建菜单", "menu", "create"),
        ("menu.update", "更新菜单", "menu", "update"),
        ("menu.delete", "删除菜单", "menu", "delete"),
        ("model.create", "创建模型", "model", "create"),
        ("model.update", "更新模型", "model", "update"),
        ("model.delete", "删除模型", "model", "delete"),
        ("notification.mark_read", "标记通知已读", "notification", "update"),
        ("provider.create", "创建供应商", "provider", "create"),
        ("provider.update", "更新供应商", "provider", "update"),
        ("provider.delete", "删除供应商", "provider", "delete"),
        ("provider.add_key", "新增供应商 Key", "provider", "create"),
        ("provider.update_key", "更新供应商 Key", "provider", "update"),
        ("provider.delete_key", "删除供应商 Key", "provider", "delete"),
        ("provider_model.create", "创建供应商模型", "provider_model", "create"),
        ("provider_model.update", "更新供应商模型", "provider_model", "update"),
        ("provider_model.delete", "删除供应商模型", "provider_model", "delete"),
        ("provider_model.sync", "同步供应商模型", "provider_model", "sync"),
        ("role.create", "创建角色", "role", "create"),
        ("role.update", "更新角色", "role", "update"),
        ("role.delete", "删除角色", "role", "delete"),
        ("role.assign_permission", "分配角色权限", "role", "update"),
        ("scheduler.trigger", "触发定时任务", "scheduler", "execute"),
        ("scheduler.update", "更新定时任务", "scheduler", "update"),
        ("system_config.update", "更新系统配置", "system_config", "update"),
        ("user.create", "创建用户", "user", "create"),
        ("user.update", "更新用户", "user", "update"),
        ("user.delete", "删除用户", "user", "delete"),
        ("user.reset_password", "重置用户密码", "user", "update"),
        ("user.assign_role", "分配用户角色", "user", "update"),
    ]
    permissions = [
        {
            "code": code,
            "name": name,
            "type": "page",
            "resource": resource,
            "action": "view",
            "description": name,
        }
        for code, name, resource in page_codes
    ]
    permissions.extend(
        {
            "code": code,
            "name": name,
            "type": "element",
            "resource": resource,
            "action": action,
            "description": name,
        }
        for code, name, resource, action in action_codes
    )
    return permissions


def default_rbac_roles() -> list[dict]:
    return [
        {
            "name": "admin",
            "display_name": "系统管理员",
            "description": "拥有全部管理权限",
            "is_system": True,
        }
    ]


async def seed_rbac_defaults(conn) -> None:
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser BOOLEAN DEFAULT FALSE"))
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT now()"))
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP"))
    await conn.execute(text("ALTER TABLE roles ADD COLUMN IF NOT EXISTS display_name VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE roles ADD COLUMN IF NOT EXISTS description TEXT"))
    await conn.execute(text("ALTER TABLE roles ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE"))
    await conn.execute(text("ALTER TABLE permissions ADD COLUMN IF NOT EXISTS name VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE permissions ADD COLUMN IF NOT EXISTS type VARCHAR(20) DEFAULT 'element'"))
    await conn.execute(text("ALTER TABLE permissions ADD COLUMN IF NOT EXISTS resource VARCHAR(50)"))
    await conn.execute(text("ALTER TABLE permissions ADD COLUMN IF NOT EXISTS action VARCHAR(20)"))
    await conn.execute(text("ALTER TABLE permissions ADD COLUMN IF NOT EXISTS description TEXT"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_permissions_code ON permissions (code)"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_user_role ON user_roles (user_id, role_id)"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_role_permission ON role_permissions (role_id, permission_id)"))

    for perm in default_rbac_permissions():
        await conn.execute(
            text(
                "INSERT INTO permissions (code, name, type, resource, action, description) "
                "VALUES (:code, :name, :type, :resource, :action, :description) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, type = EXCLUDED.type, resource = EXCLUDED.resource, "
                "action = EXCLUDED.action, description = EXCLUDED.description"
            ),
            perm,
        )
    for role in default_rbac_roles():
        await conn.execute(
            text(
                "INSERT INTO roles (name, display_name, description, is_system) "
                "VALUES (:name, :display_name, :description, :is_system) "
                "ON CONFLICT (name) DO UPDATE SET "
                "display_name = EXCLUDED.display_name, description = EXCLUDED.description, "
                "is_system = EXCLUDED.is_system"
            ),
            role,
        )
    await conn.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            "WHERE r.name = 'admin' "
            "ON CONFLICT (role_id, permission_id) DO NOTHING"
        )
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await seed_rbac_defaults(conn)
        await migrate_request_logs(conn)
        await migrate_daily_stats(conn)
        await migrate_api_keys(conn)
        await migrate_providers_and_keys(conn)
        await migrate_provider_models(conn)
        await migrate_models(conn)
        await migrate_weixin(conn)
        await migrate_documents(conn)
        await migrate_analysis(conn)
        await migrate_mcp(conn)
        await migrate_audit_logs(conn)
        await migrate_scheduler(conn)
