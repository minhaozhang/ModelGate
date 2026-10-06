"""Startup schema migrations and seed data.

Every statement is idempotent and runs on each boot inside one transaction.
Grouped by domain; init_db() calls them in dependency-safe order.
"""

from app.core.db_engine import engine
from sqlalchemy import text

REQUEST_LOG_TABLES = ("request_logs", "request_logs_history")

_DDL: list[str] = [
    "CREATE TABLE IF NOT EXISTS providers ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(50) NOT NULL UNIQUE, "
    "base_url VARCHAR(255) NOT NULL, "
    "api_key VARCHAR(255), "
    "protocol VARCHAR(20), "
    "merge_consecutive_messages BOOLEAN, "
    "is_active BOOLEAN, "
    "disabled_reason VARCHAR(255), "
    "disabled_at TIMESTAMP, "
    "reset_at TIMESTAMP, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS models ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(100) NOT NULL UNIQUE, "
    "display_name VARCHAR(100), "
    "max_tokens INTEGER, "
    "context_length INTEGER, "
    "thinking_enabled BOOLEAN, "
    "thinking_budget INTEGER, "
    "reasoning_effort TEXT, "
    "is_multimodal BOOLEAN, "
    "is_active BOOLEAN, "
    "is_virtual BOOLEAN, "
    "estimated_price DOUBLE PRECISION DEFAULT '0', "
    "tags TEXT, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS api_keys ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(100) NOT NULL, "
    "key VARCHAR(64) NOT NULL UNIQUE, "
    "email VARCHAR(255), "
    "expires_at TIMESTAMP, "
    "is_active BOOLEAN, "
    "bypass_busyness BOOLEAN, "
    "max_concurrent INTEGER, "
    "preferred_tags TEXT, "
    "last_used_at TIMESTAMP, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS mcp_servers ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(100) NOT NULL, "
    "url VARCHAR(500) NOT NULL, "
    "auth_type VARCHAR(20), "
    "auth_token TEXT, "
    "auth_header VARCHAR(100), "
    "is_active BOOLEAN, "
    "tool_prefix VARCHAR(50), "
    "last_sync_at TIMESTAMP, "
    "last_sync_error TEXT, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS users ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "username VARCHAR(50) NOT NULL UNIQUE, "
    "password_hash VARCHAR(255) NOT NULL, "
    "email VARCHAR(100), "
    "full_name VARCHAR(100), "
    "is_active BOOLEAN, "
    "is_superuser BOOLEAN, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now(), "
    "last_login TIMESTAMP"
    ")",

    "CREATE TABLE IF NOT EXISTS roles ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(50) NOT NULL UNIQUE, "
    "display_name VARCHAR(100), "
    "description TEXT, "
    "is_system BOOLEAN, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS menus ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "parent_id INTEGER REFERENCES menus(id) ON DELETE CASCADE, "
    "name VARCHAR(50) NOT NULL, "
    "display_name VARCHAR(100), "
    "icon VARCHAR(50), "
    "path VARCHAR(200), "
    "component VARCHAR(200), "
    "permission_code VARCHAR(100), "
    "sort_order INTEGER, "
    "is_visible BOOLEAN, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS weixin_accounts ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER REFERENCES api_keys(id), "
    "bot_token VARCHAR(512), "
    "ilink_bot_id VARCHAR(128), "
    "ilink_user_id VARCHAR(128), "
    "get_updates_buf TEXT, "
    "is_active BOOLEAN, "
    "reply_mode VARCHAR(10), "
    "system_prompt TEXT, "
    "model_name VARCHAR(100), "
    "login_at TIMESTAMP, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS provider_keys ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE, "
    "api_key VARCHAR(255) NOT NULL, "
    "label VARCHAR(50), "
    "max_concurrent INTEGER, "
    "is_active BOOLEAN, "
    "priority INTEGER, "
    "cost_role VARCHAR(40), "
    "disabled_reason VARCHAR(255), "
    "disabled_at TIMESTAMP, "
    "reset_at TIMESTAMP, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now(), "
    "CONSTRAINT uq_provider_key UNIQUE (provider_id, api_key)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_provider_keys_provider ON provider_keys (provider_id)",

    "CREATE TABLE IF NOT EXISTS provider_models ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_id INTEGER NOT NULL REFERENCES providers(id), "
    "model_id INTEGER NOT NULL REFERENCES models(id), "
    "model_name_override VARCHAR(100), "
    "upstream_model_name VARCHAR(100), "
    "is_active BOOLEAN, "
    "max_busyness_level INTEGER, "
    "alias VARCHAR(100), "
    "priority INTEGER, "
    "input_price_cny_per_million DOUBLE PRECISION, "
    "output_price_cny_per_million DOUBLE PRECISION, "
    "cached_input_price_cny_per_million DOUBLE PRECISION, "
    "default_cache_hit_ratio DOUBLE PRECISION DEFAULT '0', "
    "pricing_tiers JSONB, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_model ON provider_models (provider_id, model_id)",

    "CREATE TABLE IF NOT EXISTS provider_key_strategy_templates ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "name VARCHAR(100) NOT NULL, "
    "template_key VARCHAR(80) NOT NULL UNIQUE, "
    "description TEXT, "
    "is_builtin BOOLEAN, "
    "is_active BOOLEAN, "
    "config_schema JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "rule_blueprint JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_key_strategy_templates_key ON provider_key_strategy_templates (template_key)",

    "CREATE TABLE IF NOT EXISTS provider_key_strategy_assignments ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_key_id INTEGER NOT NULL REFERENCES provider_keys(id) ON DELETE CASCADE, "
    "template_id INTEGER NOT NULL REFERENCES provider_key_strategy_templates(id), "
    "enabled BOOLEAN, "
    "params JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_provider_key_strategy_assignments_key ON provider_key_strategy_assignments (provider_key_id)",

    "CREATE TABLE IF NOT EXISTS provider_key_routing_rules ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_key_id INTEGER NOT NULL REFERENCES provider_keys(id) ON DELETE CASCADE, "
    "template_assignment_id INTEGER REFERENCES provider_key_strategy_assignments(id) ON DELETE CASCADE, "
    "name VARCHAR(100), "
    "rule_type VARCHAR(30) NOT NULL, "
    "enabled BOOLEAN, "
    "priority INTEGER, "
    "start_time TIME, "
    "end_time TIME, "
    "start_date DATE, "
    "end_date DATE, "
    "weekdays VARCHAR(20), "
    "min_context_tokens INTEGER, "
    "max_context_tokens INTEGER, "
    "action VARCHAR(20) NOT NULL, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_provider_key_routing_rules_key ON provider_key_routing_rules (provider_key_id)",

    "CREATE TABLE IF NOT EXISTS provider_model_routing_rules ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_model_id INTEGER NOT NULL REFERENCES provider_models(id) ON DELETE CASCADE, "
    "name VARCHAR(100), "
    "rule_type VARCHAR(30) NOT NULL, "
    "enabled BOOLEAN, "
    "priority INTEGER, "
    "start_time TIME, "
    "end_time TIME, "
    "start_date DATE, "
    "end_date DATE, "
    "weekdays VARCHAR(20), "
    "min_context_tokens INTEGER, "
    "max_context_tokens INTEGER, "
    "provider_key_ids JSONB, "
    "action VARCHAR(20) NOT NULL, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_provider_model_routing_rules_pm ON provider_model_routing_rules (provider_model_id)",

    "CREATE TABLE IF NOT EXISTS auto_model_routes ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "virtual_model_id INTEGER NOT NULL UNIQUE REFERENCES models(id) ON DELETE CASCADE, "
    "enabled BOOLEAN, "
    "model_ids JSONB NOT NULL DEFAULT '[]', "
    "provider_model_ids JSONB NOT NULL DEFAULT '[]', "
    "route_policy JSONB NOT NULL DEFAULT '{}', "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_auto_model_routes_virtual_model ON auto_model_routes (virtual_model_id)",

    "CREATE TABLE IF NOT EXISTS api_key_models ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id), "
    "provider_model_id INTEGER NOT NULL REFERENCES provider_models(id)"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_key_model ON api_key_models (api_key_id, provider_model_id)",

    "CREATE TABLE IF NOT EXISTS api_key_model_access ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id), "
    "model_id INTEGER NOT NULL REFERENCES models(id)"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_key_model_access ON api_key_model_access (api_key_id, model_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_key_model_access_api_key_id ON api_key_model_access (api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_key_model_access_model_id ON api_key_model_access (model_id)",

    "CREATE TABLE IF NOT EXISTS api_key_tags ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
    "tag VARCHAR(50) NOT NULL, "
    "CONSTRAINT uq_api_key_tag UNIQUE (api_key_id, tag)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_api_key_tags_key ON api_key_tags (api_key_id)",

    "CREATE TABLE IF NOT EXISTS api_key_mcp_servers ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
    "mcp_server_id INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ak_mcp_unique ON api_key_mcp_servers (api_key_id, mcp_server_id)",

    "CREATE TABLE IF NOT EXISTS api_key_time_rules ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
    "rule_type VARCHAR(20) NOT NULL, "
    "allowed BOOLEAN, "
    "start_time TIME, "
    "end_time TIME, "
    "start_date DATE, "
    "end_date DATE, "
    "weekdays VARCHAR(20), "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_api_key_time_rules_key ON api_key_time_rules (api_key_id)",

    "CREATE TABLE IF NOT EXISTS request_logs ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER REFERENCES api_keys(id), "
    "provider_id INTEGER, "
    "model VARCHAR(100) NOT NULL, "
    "response TEXT, "
    "tokens JSONB, "
    "latency_ms DOUBLE PRECISION, "
    "request_context_tokens INTEGER, "
    "status VARCHAR(20) NOT NULL, "
    "upstream_status_code INTEGER, "
    "downstream_status_code INTEGER, "
    "client_ip VARCHAR(64), "
    "user_agent VARCHAR(1024), "
    "inbound_protocol VARCHAR(20), "
    "error TEXT, "
    "intent VARCHAR(20), "
    "requested_model VARCHAR(100), "
    "actual_model VARCHAR(100), "
    "provider_key_id INTEGER, "
    "provider_key_label VARCHAR(50), "
    "routing_decision JSONB, "
    "request_image_count INTEGER, "
    "fallback_tries JSONB, "
    "created_at TIMESTAMP NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMP"
    ")",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_created_at ON request_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_api_key_id ON request_logs (api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_provider_id ON request_logs (provider_id)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_status ON request_logs (status)",

    "CREATE TABLE IF NOT EXISTS request_logs_history ("
    "id INTEGER NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER, "
    "provider_id INTEGER, "
    "model VARCHAR(100) NOT NULL, "
    "response TEXT, "
    "tokens JSONB, "
    "latency_ms DOUBLE PRECISION, "
    "request_context_tokens INTEGER, "
    "status VARCHAR(20) NOT NULL, "
    "upstream_status_code INTEGER, "
    "downstream_status_code INTEGER, "
    "client_ip VARCHAR(64), "
    "user_agent VARCHAR(1024), "
    "inbound_protocol VARCHAR(20), "
    "error TEXT, "
    "intent VARCHAR(20), "
    "requested_model VARCHAR(100), "
    "actual_model VARCHAR(100), "
    "provider_key_id INTEGER, "
    "provider_key_label VARCHAR(50), "
    "routing_decision JSONB, "
    "request_image_count INTEGER, "
    "fallback_tries JSONB, "
    "created_at TIMESTAMP NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMP, "
    "archive_month VARCHAR(7) NOT NULL, "
    "archived_at TIMESTAMP NOT NULL DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_history_created_at ON request_logs_history (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_history_api_key_id ON request_logs_history (api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_history_status ON request_logs_history (status)",
    "CREATE INDEX IF NOT EXISTS idx_request_logs_history_archive_month ON request_logs_history (archive_month)",

    "CREATE TABLE IF NOT EXISTS request_contents ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "log_id INTEGER NOT NULL UNIQUE REFERENCES request_logs(id) ON DELETE CASCADE, "
    "request_messages JSONB, "
    "response_content TEXT, "
    "response_tool_calls JSONB, "
    "response_thinking TEXT, "
    "response_raw JSONB, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS provider_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "provider_name VARCHAR(50) NOT NULL, "
    "date VARCHAR(10) NOT NULL, "
    "hour INTEGER, "
    "requests INTEGER DEFAULT 0, "
    "tokens INTEGER DEFAULT 0, "
    "prompt_tokens INTEGER DEFAULT 0, "
    "completion_tokens INTEGER DEFAULT 0, "
    "errors INTEGER DEFAULT 0, "
    "timeouts INTEGER DEFAULT 0, "
    "rate_limited INTEGER DEFAULT 0"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_provider_stats_date ON provider_daily_stats (date)",

    "CREATE TABLE IF NOT EXISTS api_key_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id), "
    "date VARCHAR(10) NOT NULL, "
    "hour INTEGER, "
    "requests INTEGER DEFAULT 0, "
    "tokens INTEGER DEFAULT 0, "
    "prompt_tokens INTEGER DEFAULT 0, "
    "completion_tokens INTEGER DEFAULT 0, "
    "errors INTEGER DEFAULT 0, "
    "timeouts INTEGER DEFAULT 0, "
    "rate_limited INTEGER DEFAULT 0"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_apikey_stats_date ON api_key_daily_stats (date)",

    "CREATE TABLE IF NOT EXISTS api_key_daily_usage ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
    "date VARCHAR(10) NOT NULL, "
    "charged_cny DOUBLE PRECISION DEFAULT 0, "
    "requests_charged INTEGER DEFAULT 0, "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_key_daily_usage ON api_key_daily_usage (api_key_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_api_key_daily_usage_date ON api_key_daily_usage (date)",

    "CREATE TABLE IF NOT EXISTS api_key_model_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER NOT NULL REFERENCES api_keys(id), "
    "model_name VARCHAR(100) NOT NULL, "
    "date VARCHAR(10) NOT NULL, "
    "requests INTEGER DEFAULT 0, "
    "tokens INTEGER DEFAULT 0, "
    "prompt_tokens INTEGER DEFAULT 0, "
    "completion_tokens INTEGER DEFAULT 0, "
    "errors INTEGER DEFAULT 0, "
    "timeouts INTEGER DEFAULT 0, "
    "rate_limited INTEGER DEFAULT 0"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_apikey_model_stats_date ON api_key_model_daily_stats (date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_apikey_model_stats_unique ON api_key_model_daily_stats (api_key_id, model_name, date)",

    "CREATE TABLE IF NOT EXISTS model_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "model_name VARCHAR(100) NOT NULL, "
    "provider_name VARCHAR(50), "
    "date VARCHAR(10) NOT NULL, "
    "requests INTEGER DEFAULT 0, "
    "tokens INTEGER DEFAULT 0, "
    "prompt_tokens INTEGER DEFAULT 0, "
    "completion_tokens INTEGER DEFAULT 0, "
    "errors INTEGER DEFAULT 0, "
    "timeouts INTEGER DEFAULT 0, "
    "rate_limited INTEGER DEFAULT 0"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_model_stats_date ON model_daily_stats (date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_stats_unique ON model_daily_stats (model_name, provider_name, date)",

    "CREATE TABLE IF NOT EXISTS tag_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "date VARCHAR(10) NOT NULL, "
    "tag VARCHAR(50) NOT NULL DEFAULT '', "
    "api_key_id INTEGER NOT NULL, "
    "key_name VARCHAR(100) NOT NULL DEFAULT '', "
    "requests INTEGER DEFAULT 0, "
    "prompt_tokens INTEGER DEFAULT 0, "
    "completion_tokens INTEGER DEFAULT 0, "
    "tokens INTEGER DEFAULT 0, "
    "cost_cny DOUBLE PRECISION DEFAULT '0'"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_daily_stats ON tag_daily_stats (date, tag, api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_tag_daily_stats_date ON tag_daily_stats (date)",
    "CREATE INDEX IF NOT EXISTS idx_tag_daily_stats_tag ON tag_daily_stats (tag)",

    "CREATE TABLE IF NOT EXISTS hourly_peak_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "date VARCHAR(10) NOT NULL, "
    "hour INTEGER NOT NULL, "
    "max_concurrency INTEGER DEFAULT 0, "
    "max_tokens_per_second DOUBLE PRECISION DEFAULT '0', "
    "updated_at TIMESTAMP DEFAULT NOW()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_hourly_peak_stats ON hourly_peak_stats (date, hour)",

    "CREATE TABLE IF NOT EXISTS daily_reports ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "date VARCHAR(10) NOT NULL, "
    "level VARCHAR(10) NOT NULL DEFAULT 'info', "
    "summary TEXT NOT NULL DEFAULT '', "
    "sections JSONB, "
    "created_at TIMESTAMP NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMP"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_reports_date ON daily_reports (date)",

    "CREATE TABLE IF NOT EXISTS analysis_records ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "analysis_type VARCHAR(50) NOT NULL, "
    "scope_key VARCHAR(255) NOT NULL, "
    "status VARCHAR(20) NOT NULL, "
    "language VARCHAR(10), "
    "model_used VARCHAR(150), "
    "template_id VARCHAR(100), "
    "template_version VARCHAR(50), "
    "params_json JSONB, "
    "content TEXT, "
    "error TEXT, "
    "expires_at TIMESTAMP, "
    "progress VARCHAR(200), "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_records_type_scope ON analysis_records (analysis_type, scope_key)",

    "CREATE TABLE IF NOT EXISTS analysis_subtasks ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "analysis_record_id INTEGER NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE, "
    "step_key VARCHAR(100) NOT NULL, "
    "step_label VARCHAR(150) NOT NULL, "
    "status VARCHAR(20) NOT NULL, "
    "sort_order INTEGER, "
    "attempt_count INTEGER, "
    "max_attempts INTEGER, "
    "output JSONB, "
    "error TEXT, "
    "started_at TIMESTAMP, "
    "finished_at TIMESTAMP, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_subtasks_record_step ON analysis_subtasks (analysis_record_id, step_key)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_subtasks_status ON analysis_subtasks (status)",

    "CREATE TABLE IF NOT EXISTS analysis_artifacts ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "analysis_record_id INTEGER NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE, "
    "subtask_id INTEGER REFERENCES analysis_subtasks(id) ON DELETE SET NULL, "
    "artifact_key VARCHAR(100) NOT NULL, "
    "artifact_type VARCHAR(50) NOT NULL, "
    "title VARCHAR(150), "
    "path TEXT, "
    "status VARCHAR(20) NOT NULL, "
    "meta JSONB, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_artifacts_record_key ON analysis_artifacts (analysis_record_id, artifact_key)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_artifacts_status ON analysis_artifacts (status)",

    "CREATE TABLE IF NOT EXISTS documents ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "title VARCHAR(200) NOT NULL, "
    "slug VARCHAR(200) NOT NULL UNIQUE, "
    "content TEXT NOT NULL, "
    "category VARCHAR(50), "
    "filename VARCHAR(255), "
    "is_published BOOLEAN, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_slug ON documents (slug)",
    "CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category)",

    "CREATE TABLE IF NOT EXISTS document_files ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, "
    "filename VARCHAR(255) NOT NULL, "
    "object_name VARCHAR(500) NOT NULL, "
    "file_type VARCHAR(20) NOT NULL, "
    "file_size INTEGER, "
    "content_type VARCHAR(100), "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_document_files_doc_id ON document_files (document_id)",

    "CREATE TABLE IF NOT EXISTS weixin_context_tokens ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "account_id INTEGER NOT NULL REFERENCES weixin_accounts(id), "
    "user_id VARCHAR(128) NOT NULL, "
    "context_token TEXT, "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_weixin_ctx_account_user ON weixin_context_tokens (account_id, user_id)",

    "CREATE TABLE IF NOT EXISTS weixin_messages ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "account_id INTEGER NOT NULL REFERENCES weixin_accounts(id), "
    "direction VARCHAR(3) NOT NULL, "
    "from_user VARCHAR(128) NOT NULL, "
    "to_user VARCHAR(128) NOT NULL, "
    "text TEXT, "
    "context_token TEXT, "
    "status VARCHAR(20), "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_weixin_msg_account ON weixin_messages (account_id)",
    "CREATE INDEX IF NOT EXISTS idx_weixin_msg_status ON weixin_messages (status)",
    "CREATE INDEX IF NOT EXISTS idx_weixin_msg_created ON weixin_messages (created_at)",

    "CREATE TABLE IF NOT EXISTS mcp_call_logs ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "api_key_id INTEGER REFERENCES api_keys(id), "
    "mcp_server_id INTEGER REFERENCES mcp_servers(id), "
    "tool_name VARCHAR(200) NOT NULL, "
    "arguments JSONB, "
    "result TEXT, "
    "is_error BOOLEAN, "
    "latency_ms DOUBLE PRECISION, "
    "client_ip VARCHAR(64), "
    "user_agent VARCHAR(1024), "
    "error TEXT, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_created_at ON mcp_call_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_server_id ON mcp_call_logs (mcp_server_id)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_call_logs_tool_name ON mcp_call_logs (tool_name)",

    "CREATE TABLE IF NOT EXISTS mcp_call_daily_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "mcp_server_id INTEGER NOT NULL REFERENCES mcp_servers(id), "
    "date VARCHAR(10) NOT NULL, "
    "hour INTEGER, "
    "calls INTEGER, "
    "errors INTEGER, "
    "avg_latency_ms DOUBLE PRECISION"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_mcp_stats_date ON mcp_call_daily_stats (date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_stats_unique ON mcp_call_daily_stats (mcp_server_id, date, hour)",

    "CREATE TABLE IF NOT EXISTS notifications ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "type VARCHAR(20) NOT NULL, "
    "level VARCHAR(20) NOT NULL, "
    "title VARCHAR(255) NOT NULL, "
    "body TEXT, "
    "target_api_key_id INTEGER, "
    "is_read_by_admin BOOLEAN, "
    "read_api_key_ids JSONB, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications (type)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_target ON notifications (target_api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications (created_at)",

    "CREATE TABLE IF NOT EXISTS model_speed_stats ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "period_start TIMESTAMP NOT NULL, "
    "provider_name VARCHAR(50) NOT NULL DEFAULT '', "
    "model_name VARCHAR(100) NOT NULL DEFAULT '', "
    "requests INTEGER NOT NULL DEFAULT 0, "
    "output_tokens BIGINT NOT NULL DEFAULT 0, "
    "stream_ms FLOAT NOT NULL DEFAULT 0"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_speed_stats ON model_speed_stats (period_start, provider_name, model_name)",
    "CREATE INDEX IF NOT EXISTS idx_model_speed_stats_period ON model_speed_stats (period_start)",

    "CREATE TABLE IF NOT EXISTS ip_tags ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "ip VARCHAR(64) NOT NULL, "
    "tag VARCHAR(50) NOT NULL, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_tags ON ip_tags (ip, tag)",
    "CREATE INDEX IF NOT EXISTS idx_ip_tags_ip ON ip_tags (ip)",

    "CREATE TABLE IF NOT EXISTS scheduler_tasks ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "task_id VARCHAR(100) NOT NULL UNIQUE, "
    "name VARCHAR(200) NOT NULL, "
    "description TEXT, "
    "cron_expression VARCHAR(50) NOT NULL, "
    "default_cron VARCHAR(50) NOT NULL, "
    "is_paused BOOLEAN, "
    "last_run_at TIMESTAMP, "
    "last_duration_ms INTEGER, "
    "last_status VARCHAR(20), "
    "last_error TEXT, "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",

    "CREATE TABLE IF NOT EXISTS scheduler_task_logs ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "task_id VARCHAR(100) NOT NULL, "
    "status VARCHAR(20) NOT NULL, "
    "started_at TIMESTAMP NOT NULL, "
    "finished_at TIMESTAMP, "
    "duration_ms INTEGER, "
    "error TEXT, "
    "result_summary TEXT"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_task_logs_started ON scheduler_task_logs (started_at)",

    "CREATE TABLE IF NOT EXISTS system_settings ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "category VARCHAR(50) NOT NULL, "
    "\"key\" VARCHAR(100) NOT NULL UNIQUE, "
    "\"value\" TEXT, "
    "description TEXT, "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_system_settings_category ON system_settings (category)",
    "CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings (\"key\")",

    "CREATE TABLE IF NOT EXISTS user_roles ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE, "
    "created_at TIMESTAMP DEFAULT now(), "
    "CONSTRAINT uq_user_role UNIQUE (user_id, role_id)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles (role_id)",

    "CREATE TABLE IF NOT EXISTS permissions ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "code VARCHAR(100) NOT NULL UNIQUE, "
    "name VARCHAR(100), "
    "type VARCHAR(20) NOT NULL, "
    "resource VARCHAR(50), "
    "action VARCHAR(20), "
    "description TEXT, "
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_permissions_code ON permissions (code)",
    "CREATE INDEX IF NOT EXISTS idx_permissions_resource ON permissions (resource)",

    "CREATE TABLE IF NOT EXISTS role_permissions ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE, "
    "permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE, "
    "created_at TIMESTAMP DEFAULT now(), "
    "CONSTRAINT uq_role_permission UNIQUE (role_id, permission_id)"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions (role_id)",
    "CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id ON role_permissions (permission_id)",

    "CREATE TABLE IF NOT EXISTS audit_logs ("
    "id SERIAL NOT NULL PRIMARY KEY, "
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
    "created_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at)",

    "CREATE TABLE IF NOT EXISTS ip_locations ("
    "id SERIAL NOT NULL PRIMARY KEY, "
    "ip VARCHAR(64) NOT NULL UNIQUE, "
    "province VARCHAR(100), "
    "city VARCHAR(100), "
    "adcode VARCHAR(20), "
    "rectangle VARCHAR(200), "
    "loc VARCHAR(100), "
    "country VARCHAR(50), "
    "isp VARCHAR(200), "
    "source VARCHAR(20) DEFAULT 'amap', "
    "created_at TIMESTAMP DEFAULT now(), "
    "updated_at TIMESTAMP DEFAULT now()"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_ip_locations_ip ON ip_locations (ip)",
    "ALTER TABLE ip_locations ADD COLUMN IF NOT EXISTS loc VARCHAR(100)",
    "ALTER TABLE ip_locations ADD COLUMN IF NOT EXISTS country VARCHAR(50)",
    "ALTER TABLE ip_locations ADD COLUMN IF NOT EXISTS isp VARCHAR(200)",
]


async def create_tables(conn) -> None:
    for stmt in _DDL:
        await conn.execute(text(stmt))


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
            "first_chunk_ms DOUBLE PRECISION",
            "wait_ms DOUBLE PRECISION",
            "request_image_count INTEGER",
            "fallback_tries JSONB",
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

    # request_logs_all must be dropped first: the speed column changes below
    # may DROP COLUMN, which the existing view would block via dependency.
    await conn.execute(text("DROP VIEW IF EXISTS request_logs_all"))

    # Per-request speed column hardening (2026-09-30 incident):
    # ADD COLUMN ... GENERATED ALWAYS rewrites the whole table under an
    # ACCESS EXCLUSIVE lock - minutes on production-sized tables, stalling
    # startup and queueing live writes. Therefore:
    # - request_logs_history gets a PLAIN column (metadata-only, instant);
    #   the archive job copies values into it (see stats_aggregator).
    # - request_logs keeps its generated column (auto-computed on write).
    #   Creating or swapping it (v1 -> v2 formula) only happens under a short
    #   lock_timeout inside a savepoint; if the lock is busy the attempt is
    #   skipped and retried on the next restart - startup NEVER waits.
    from app.core.db_models import REQUEST_SPEED_EXPR

    # history: any existing column (v1/v2 generated) -> plain, no rewrite.
    await conn.execute(
        text("ALTER TABLE request_logs_history DROP COLUMN IF EXISTS speed_tokens_per_s")
    )
    await conn.execute(
        text(
            "ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS "
            "speed_tokens_per_s DOUBLE PRECISION"
        )
    )

    # live table: detect current expression (PG deparses "N - 1" as
    # "N - (1)::numeric", which is the v2 fingerprint).
    live_expr = (
        await conn.execute(
            text(
                "SELECT generation_expression FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'request_logs' "
                "AND column_name = 'speed_tokens_per_s'"
            )
        )
    ).scalar()
    needs_swap = live_expr is not None and "- (1)::numeric" not in live_expr
    needs_add = live_expr is None
    if needs_swap:
        # The swap rewrites the live table under an exclusive lock for the
        # whole rewrite (~10s/GB measured); lock_timeout bounds only the lock
        # WAIT, not the hold. v1 vs v2 differ by <=2% (N vs N-1), so keep v1
        # rather than stall live writes on a big table.
        import logging

        live_bytes = (
            await conn.execute(text("SELECT pg_relation_size('request_logs')"))
        ).scalar()
        if (live_bytes or 0) > 256 * 1024 * 1024:
            needs_swap = False
            logging.getLogger(__name__).warning(
                "request_logs speed v1->v2 swap skipped: table too large "
                "(%d bytes > 256MB rewrite risk); keeping v1 formula",
                live_bytes,
            )
    if needs_swap or needs_add:
        import logging

        await conn.execute(text("SAVEPOINT speed_live_column"))
        try:
            if needs_swap:
                await conn.execute(
                    text("ALTER TABLE request_logs DROP COLUMN speed_tokens_per_s")
                )
            await conn.execute(
                text(
                    "ALTER TABLE request_logs ADD COLUMN speed_tokens_per_s DOUBLE PRECISION "
                    f"GENERATED ALWAYS AS ({REQUEST_SPEED_EXPR}) STORED"
                )
            )
            await conn.execute(text("RELEASE SAVEPOINT speed_live_column"))
        except Exception as exc:  # lock timeout (or worse): keep old column
            await conn.execute(text("ROLLBACK TO SAVEPOINT speed_live_column"))
            await conn.execute(text("RELEASE SAVEPOINT speed_live_column"))
            logging.getLogger(__name__).warning(
                "request_logs speed column %s skipped (%s); will retry next restart",
                "v1->v2 swap" if needs_swap else "creation",
                exc,
            )

    # request_logs_all: live + archived union view.
    columns = (
        "id, api_key_id, provider_id, model, response, tokens, latency_ms, first_chunk_ms, wait_ms, "
        "speed_tokens_per_s, "
        "request_context_tokens, status, upstream_status_code, downstream_status_code, client_ip, user_agent, "
        "inbound_protocol, error, intent, requested_model, actual_model, provider_key_id, provider_key_label, routing_decision, request_image_count, fallback_tries, created_at, updated_at"
    )
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

    await conn.execute(text("DROP INDEX IF EXISTS idx_request_contents_log_id"))


async def migrate_daily_stats(conn) -> None:
    for table_name in (
        "provider_daily_stats",
        "api_key_daily_stats",
        "api_key_model_daily_stats",
        "model_daily_stats",
    ):
        for column_sql in (
            "prompt_tokens INTEGER DEFAULT 0",
            "completion_tokens INTEGER DEFAULT 0",
            "timeouts INTEGER DEFAULT 0",
        ):
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN IF NOT EXISTS {column_sql}"
                )
            )

    # One-time split backfill: recompute prompt/completion/timeouts and
    # error-only errors from the request_logs_all view (live + archived;
    # rate-limited rows contribute zero to all of these). Guarded by a
    # system_settings flag so it never runs twice.
    flag_result = await conn.execute(
        text(
            "SELECT 1 FROM system_settings "
            "WHERE \"key\" = 'daily_stats_split_backfilled' LIMIT 1"
        )
    )
    if flag_result.fetchone() is None:
        agg_cols = (
            "SUM(COALESCE((rl.tokens->>'prompt_tokens')::bigint, 0)) AS prompt_tokens, "
            "SUM(COALESCE((rl.tokens->>'completion_tokens')::bigint, 0)) AS completion_tokens, "
            "SUM(CASE WHEN rl.status = 'timeout' THEN 1 ELSE 0 END) AS timeouts, "
            "SUM(CASE WHEN rl.status = 'error' THEN 1 ELSE 0 END) AS errors"
        )
        set_clause = (
            "prompt_tokens = COALESCE(a.prompt_tokens, 0), "
            "completion_tokens = COALESCE(a.completion_tokens, 0), "
            "timeouts = COALESCE(a.timeouts, 0), "
            "errors = COALESCE(a.errors, 0)"
        )
        await conn.execute(
            text(
                "UPDATE model_daily_stats mds SET "
                + set_clause
                + " FROM ("
                "SELECT to_char(rl.created_at, 'YYYY-MM-DD') AS d, rl.model, p.name, "
                + agg_cols
                + " FROM request_logs_all rl "
                "LEFT JOIN providers p ON p.id = rl.provider_id "
                "WHERE rl.status NOT IN ('rate_limited', 'local_rate_limited') "
                "GROUP BY to_char(rl.created_at, 'YYYY-MM-DD'), rl.model, p.name"
                ") a "
                "WHERE mds.date = a.d AND mds.model_name = a.model "
                "AND mds.provider_name IS NOT DISTINCT FROM a.name"
            )
        )
        await conn.execute(
            text(
                "UPDATE provider_daily_stats pds SET "
                + set_clause
                + " FROM ("
                "SELECT to_char(rl.created_at, 'YYYY-MM-DD') AS d, p.name, "
                + agg_cols
                + " FROM request_logs_all rl "
                "JOIN providers p ON p.id = rl.provider_id "
                "WHERE rl.status NOT IN ('rate_limited', 'local_rate_limited') "
                "GROUP BY to_char(rl.created_at, 'YYYY-MM-DD'), p.name"
                ") a "
                "WHERE pds.date = a.d AND pds.provider_name = a.name"
            )
        )
        await conn.execute(
            text(
                "UPDATE api_key_daily_stats akds SET "
                + set_clause
                + " FROM ("
                "SELECT to_char(rl.created_at, 'YYYY-MM-DD') AS d, rl.api_key_id, "
                + agg_cols
                + " FROM request_logs_all rl "
                "WHERE rl.status NOT IN ('rate_limited', 'local_rate_limited') "
                "GROUP BY to_char(rl.created_at, 'YYYY-MM-DD'), rl.api_key_id"
                ") a "
                "WHERE akds.date = a.d AND akds.api_key_id = a.api_key_id"
            )
        )
        await conn.execute(
            text(
                "UPDATE api_key_model_daily_stats akmds SET "
                + set_clause
                + " FROM ("
                "SELECT to_char(rl.created_at, 'YYYY-MM-DD') AS d, rl.api_key_id, rl.model, "
                + agg_cols
                + " FROM request_logs_all rl "
                "WHERE rl.status NOT IN ('rate_limited', 'local_rate_limited') "
                "GROUP BY to_char(rl.created_at, 'YYYY-MM-DD'), rl.api_key_id, rl.model"
                ") a "
                "WHERE akmds.date = a.d AND akmds.api_key_id = a.api_key_id "
                "AND akmds.model_name = a.model"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO system_settings (category, \"key\", \"value\", description) "
                "VALUES ('migration', 'daily_stats_split_backfilled', 'done', "
                "'Split prompt/completion/timeouts/error backfill for daily stats tables') "
                "ON CONFLICT (\"key\") DO NOTHING"
            )
        )


async def migrate_api_keys(conn) -> None:
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP"))
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS email VARCHAR(255)"))
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS max_concurrent INTEGER"))
    await conn.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS per_key_concurrency INTEGER"))
    await conn.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS per_key_concurrency_tiers JSONB"))
    await conn.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS coding_only BOOLEAN DEFAULT FALSE"))
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP"))
    await conn.execute(
        text("UPDATE api_keys SET expires_at = now() + interval '1 year' WHERE expires_at IS NULL")
    )
    await conn.execute(
        text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS bypass_busyness BOOLEAN DEFAULT FALSE")
    )
    await conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS preferred_tags TEXT"))
    await conn.execute(
        text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS daily_quota_cny DOUBLE PRECISION")
    )
    await conn.execute(
        text("ALTER TABLE api_keys DROP COLUMN IF EXISTS model_concurrency")
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
        text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS disabled_by VARCHAR(20)")
    )
    await conn.execute(
        text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS disabled_by VARCHAR(20)")
    )
    await conn.execute(
        text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS disable_schedule JSONB")
    )
    await conn.execute(
        text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS disable_schedule JSONB")
    )
    await conn.execute(
        text("UPDATE providers SET protocol = 'openai' WHERE protocol IS NULL OR protocol = ''")
    )
    await conn.execute(
        text("ALTER TABLE providers DROP COLUMN IF EXISTS max_concurrent")
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

    # Legacy fallback column is gone: keys all unavailable means provider
    # unavailable. Legacy column data is intentionally discarded.
    await conn.execute(
        text("ALTER TABLE providers DROP COLUMN IF EXISTS api_key")
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
            "ALTER TABLE provider_model_routing_rules "
            "ADD COLUMN IF NOT EXISTS provider_key_ids JSONB"
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
        "context_hard_limit INTEGER",
        "max_concurrent INTEGER",
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
    await conn.execute(text("DROP INDEX IF EXISTS idx_analysis_records_status"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_analysis_records_expires_at"))


async def migrate_mcp(conn) -> None:
    await conn.execute(text("ALTER TABLE mcp_servers DROP COLUMN IF EXISTS api_key_id"))


async def migrate_tag_stats(conn) -> None:
    await conn.execute(
        text("ALTER TABLE api_key_daily_stats ADD COLUMN IF NOT EXISTS cost_cny DOUBLE PRECISION DEFAULT '0'")
    )


async def migrate_provider_key_stats(conn) -> None:
    # nullable on purpose: NULL marks pre-migration rows not yet re-aggregated
    await conn.execute(
        text("ALTER TABLE provider_daily_stats ADD COLUMN IF NOT EXISTS cost_cny DOUBLE PRECISION")
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS provider_key_daily_stats ("
            "id SERIAL NOT NULL PRIMARY KEY, "
            "date VARCHAR(10) NOT NULL, "
            "provider_key_id INTEGER NOT NULL, "
            "provider_key_label VARCHAR(50), "
            "provider_name VARCHAR(50), "
            "requests INTEGER DEFAULT 0, "
            "tokens INTEGER DEFAULT 0, "
            "prompt_tokens INTEGER DEFAULT 0, "
            "completion_tokens INTEGER DEFAULT 0, "
            "errors INTEGER DEFAULT 0, "
            "timeouts INTEGER DEFAULT 0, "
            "rate_limited INTEGER DEFAULT 0, "
            "cost_cny DOUBLE PRECISION DEFAULT '0'"
            ")"
        )
    )
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_key_stats ON provider_key_daily_stats (provider_key_id, date)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_provider_key_stats_date ON provider_key_daily_stats (date)")
    )


async def migrate_audit_logs(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_user_id"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_resource"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_audit_logs_action"))


async def migrate_scheduler(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_task_logs_task"))


def default_rbac_permissions() -> list[dict]:
    page_codes = [
        ("page.api_keys", "API Key 页面", "api_keys"),
        ("page.documents", "文档页面", "documents"),
        ("page.logs.requests", "请求日志页面", "logs"),
        ("page.models", "标准模型页面", "models"),
        ("page.provider_models", "供应商模型页面", "provider_models"),
        ("page.providers", "供应商页面", "providers"),
        ("page.daily_reports", "每日简报页面", "daily_reports"),
        ("page.report_center", "报表中心页面", "report_center"),
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
        ("menu.create", "创建菜单", "menu", "create"),
        ("menu.update", "更新菜单", "menu", "update"),
        ("menu.delete", "删除菜单", "menu", "delete"),
        ("model.create", "创建模型", "model", "create"),
        ("model.update", "更新模型", "model", "update"),
        ("model.delete", "删除模型", "model", "delete"),
        ("notification.create", "发布公告", "notification", "create"),
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
        # Guard the WHOLE startup transaction: any DDL stuck waiting on a
        # lock (busy table during a rolling deploy, leaked idle-in-transaction
        # session) fails fast with a clear lock-timeout error instead of
        # hanging startup until the health check kills the container
        # (2026-09-30 incident). Optional/skippable steps use savepoints to
        # degrade gracefully; the rest abort startup loudly, which is the
        # correct signal to stop the old instance first.
        await conn.execute(text("SET LOCAL lock_timeout = '15s'"))
        await create_tables(conn)
        await seed_rbac_defaults(conn)
        # One-time: slow the auto-reenable sweep from 30min to hourly (only
        # rows still on the old default; customized values are untouched).
        await conn.execute(
            text(
                "UPDATE scheduler_tasks SET cron_expression = '0 * * * *', "
                "default_cron = '0 * * * *' "
                "WHERE task_id = 'auto_reenable_disabled' "
                "AND cron_expression = '*/30 * * * *'"
            )
        )
        # One-time: strip stray leading/trailing whitespace from provider
        # base URLs (breaks httpx: "unknown url type: '/%20https://...'").
        await conn.execute(text("UPDATE providers SET base_url = TRIM(base_url)"))
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
        await migrate_tag_stats(conn)
        await migrate_provider_key_stats(conn)
        await migrate_audit_logs(conn)
        await migrate_scheduler(conn)
