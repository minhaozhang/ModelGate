"""ORM models. Importing this module registers every table on Base.metadata."""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import registry

from app.core.db_engine import Base

# ==================== Providers & provider keys ====================


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    base_url = Column(String(255), nullable=False)
    api_key = Column(String(255), nullable=True)
    protocol = Column(String(20), default="openai")
    merge_consecutive_messages = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    disabled_reason = Column(String(255), nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    reset_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    api_key = Column(String(255), nullable=False)
    label = Column(String(50), nullable=True)
    max_concurrent = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    cost_role = Column(String(40), default="standard")
    disabled_reason = Column(String(255), nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    reset_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider_id", "api_key", name="uq_provider_key"),
        Index("idx_provider_keys_provider", "provider_id"),
    )


class ProviderKeyStrategyTemplate(Base):
    __tablename__ = "provider_key_strategy_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    template_key = Column(String(80), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_builtin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    config_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    rule_blueprint = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_provider_key_strategy_templates_key", "template_key", unique=True),
    )


class ProviderKeyStrategyAssignment(Base):
    __tablename__ = "provider_key_strategy_assignments"

    id = Column(Integer, primary_key=True)
    provider_key_id = Column(Integer, ForeignKey("provider_keys.id", ondelete="CASCADE"), nullable=False)
    template_id = Column(Integer, ForeignKey("provider_key_strategy_templates.id"), nullable=False)
    enabled = Column(Boolean, default=True)
    params = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_provider_key_strategy_assignments_key", "provider_key_id"),
    )


class ProviderKeyRoutingRule(Base):
    __tablename__ = "provider_key_routing_rules"

    id = Column(Integer, primary_key=True)
    provider_key_id = Column(Integer, ForeignKey("provider_keys.id", ondelete="CASCADE"), nullable=False)
    template_assignment_id = Column(
        Integer,
        ForeignKey("provider_key_strategy_assignments.id", ondelete="CASCADE"),
        nullable=True,
    )
    name = Column(String(100), nullable=True)
    rule_type = Column(String(30), nullable=False, default="custom")
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    weekdays = Column(String(20), nullable=True)
    min_context_tokens = Column(Integer, nullable=True)
    max_context_tokens = Column(Integer, nullable=True)
    action = Column(String(20), nullable=False, default="prefer")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_provider_key_routing_rules_key", "provider_key_id"),
    )


class ProviderModelRoutingRule(Base):
    __tablename__ = "provider_model_routing_rules"

    id = Column(Integer, primary_key=True)
    provider_model_id = Column(Integer, ForeignKey("provider_models.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=True)
    rule_type = Column(String(30), nullable=False, default="custom")
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    weekdays = Column(String(20), nullable=True)
    min_context_tokens = Column(Integer, nullable=True)
    max_context_tokens = Column(Integer, nullable=True)
    provider_key_ids = Column(JSONB, nullable=True)
    action = Column(String(20), nullable=False, default="prefer")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_provider_model_routing_rules_pm", "provider_model_id"),
    )


# ==================== Models & provider bindings ====================


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    max_tokens = Column(Integer, default=131072)
    context_length = Column(Integer, default=204800)
    context_hard_limit = Column(Integer, nullable=True)
    thinking_enabled = Column(Boolean, default=True)
    thinking_budget = Column(Integer, default=8192)
    reasoning_effort = Column(Text, nullable=True)
    is_multimodal = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_virtual = Column(Boolean, default=False)
    estimated_price = Column(Float, nullable=True, server_default="0")
    tags = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ProviderModel(Base):
    __tablename__ = "provider_models"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_name_override = Column(String(100), nullable=True)
    upstream_model_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    max_busyness_level = Column(Integer, nullable=True)
    alias = Column(String(100), nullable=True)
    priority = Column(Integer, default=0)
    input_price_cny_per_million = Column(Float, nullable=True)
    output_price_cny_per_million = Column(Float, nullable=True)
    cached_input_price_cny_per_million = Column(Float, nullable=True)
    default_cache_hit_ratio = Column(Float, nullable=True, server_default="0")
    pricing_tiers = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_provider_model", "provider_id", "model_id", unique=True),
    )


class AutoModelRoute(Base):
    __tablename__ = "auto_model_routes"

    id = Column(Integer, primary_key=True)
    virtual_model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled = Column(Boolean, default=False)
    model_ids = Column(JSONB, nullable=False, server_default="[]")
    provider_model_ids = Column(JSONB, nullable=False, server_default="[]")
    route_policy = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_auto_model_routes_virtual_model", "virtual_model_id"),
    )


# ==================== API keys & access control ====================


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    key = Column(String(64), unique=True, nullable=False)
    email = Column(String(255), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    bypass_busyness = Column(Boolean, default=False)
    preferred_tags = Column(Text, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ApiKeyModel(Base):
    __tablename__ = "api_key_models"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    provider_model_id = Column(
        Integer, ForeignKey("provider_models.id"), nullable=False
    )

    __table_args__ = (
        Index("idx_api_key_model", "api_key_id", "provider_model_id", unique=True),
    )


class ApiKeyModelAccess(Base):
    __tablename__ = "api_key_model_access"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)

    __table_args__ = (
        Index("idx_api_key_model_access", "api_key_id", "model_id", unique=True),
        Index("idx_api_key_model_access_api_key_id", "api_key_id"),
        Index("idx_api_key_model_access_model_id", "model_id"),
    )


class ApiKeyTag(Base):
    __tablename__ = "api_key_tags"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String(50), nullable=False)

    __table_args__ = (
        Index("idx_api_key_tags_key", "api_key_id"),
        UniqueConstraint("api_key_id", "tag", name="uq_api_key_tag"),
    )


class ApiKeyMcpServer(Base):
    __tablename__ = "api_key_mcp_servers"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    mcp_server_id = Column(Integer, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        Index("idx_ak_mcp_unique", "api_key_id", "mcp_server_id", unique=True),
    )


class ApiKeyTimeRule(Base):
    __tablename__ = "api_key_time_rules"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(
        Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    rule_type = Column(String(20), nullable=False)
    allowed = Column(Boolean, default=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    weekdays = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (Index("idx_api_key_time_rules_key", "api_key_id"),)


# ==================== Request logs ====================


class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    provider_id = Column(Integer, nullable=True)
    model = Column(String(100), nullable=False)
    response = Column(Text, nullable=True)
    tokens = Column(JSONB, nullable=True)
    latency_ms = Column(Float, nullable=True)
    request_context_tokens = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)
    upstream_status_code = Column(Integer, nullable=True)
    downstream_status_code = Column(Integer, nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    inbound_protocol = Column(String(20), nullable=True)
    error = Column(Text, nullable=True)
    intent = Column(String(20), nullable=True)
    requested_model = Column(String(100), nullable=True)
    actual_model = Column(String(100), nullable=True)
    provider_key_id = Column(Integer, nullable=True)
    provider_key_label = Column(String(50), nullable=True)
    routing_decision = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, index=True, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_request_logs_api_key_id", "api_key_id"),
        Index("idx_request_logs_provider_id", "provider_id"),
        Index("idx_request_logs_status", "status"),
    )


class RequestLogHistory(Base):
    __tablename__ = "request_logs_history"

    id = Column(Integer, primary_key=True, autoincrement=False)
    api_key_id = Column(Integer, nullable=True)
    provider_id = Column(Integer, nullable=True)
    model = Column(String(100), nullable=False)
    response = Column(Text, nullable=True)
    tokens = Column(JSONB, nullable=True)
    latency_ms = Column(Float, nullable=True)
    request_context_tokens = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)
    upstream_status_code = Column(Integer, nullable=True)
    downstream_status_code = Column(Integer, nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    inbound_protocol = Column(String(20), nullable=True)
    error = Column(Text, nullable=True)
    intent = Column(String(20), nullable=True)
    requested_model = Column(String(100), nullable=True)
    actual_model = Column(String(100), nullable=True)
    provider_key_id = Column(Integer, nullable=True)
    provider_key_label = Column(String(50), nullable=True)
    routing_decision = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, index=True, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)
    archive_month = Column(String(7), nullable=False)
    archived_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_request_logs_history_api_key_id", "api_key_id"),
        Index("idx_request_logs_history_status", "status"),
        Index("idx_request_logs_history_archive_month", "archive_month"),
    )


class RequestContent(Base):
    __tablename__ = "request_contents"

    id = Column(Integer, primary_key=True)
    log_id = Column(Integer, ForeignKey("request_logs.id", ondelete="CASCADE"), unique=True, nullable=False)
    request_messages = Column(JSONB, nullable=True)
    response_content = Column(Text, nullable=True)
    response_tool_calls = Column(JSONB, nullable=True)
    response_thinking = Column(Text, nullable=True)
    response_raw = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# Read-only mapping over the request_logs_all view (live + archived).
read_registry = registry()
request_logs_all_table = read_registry.metadata.tables.get("request_logs_all")
if request_logs_all_table is None:
    request_logs_all_table = Table(
        "request_logs_all",
        read_registry.metadata,
        Column("id", Integer, primary_key=True),
        Column("api_key_id", Integer),
        Column("provider_id", Integer),
        Column("model", String(100)),
        Column("response", Text),
        Column("tokens", JSONB),
        Column("latency_ms", Float),
        Column("request_context_tokens", Integer),
        Column("status", String(20)),
        Column("upstream_status_code", Integer),
        Column("downstream_status_code", Integer),
        Column("client_ip", String(64)),
        Column("user_agent", String(1024)),
        Column("inbound_protocol", String(20)),
        Column("error", Text),
        Column("intent", String(20)),
        Column("requested_model", String(100)),
        Column("actual_model", String(100)),
        Column("provider_key_id", Integer),
        Column("provider_key_label", String(50)),
        Column("routing_decision", JSONB),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )


class RequestLogRead:
    pass


read_registry.map_imperatively(RequestLogRead, request_logs_all_table)

# ==================== Daily stats ====================


class ProviderDailyStat(Base):
    __tablename__ = "provider_daily_stats"

    id = Column(Integer, primary_key=True)
    provider_name = Column(String(50), nullable=False)
    date = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=True)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    timeouts = Column(Integer, default=0)
    rate_limited = Column(Integer, default=0)

    __table_args__ = (Index("idx_provider_stats_date", "date"),)


class ApiKeyDailyStat(Base):
    __tablename__ = "api_key_daily_stats"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    date = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=True)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    timeouts = Column(Integer, default=0)
    rate_limited = Column(Integer, default=0)

    __table_args__ = (Index("idx_apikey_stats_date", "date"),)


class ApiKeyModelDailyStat(Base):
    __tablename__ = "api_key_model_daily_stats"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    model_name = Column(String(100), nullable=False)
    date = Column(String(10), nullable=False)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    timeouts = Column(Integer, default=0)
    rate_limited = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_apikey_model_stats_date", "date"),
        Index(
            "idx_apikey_model_stats_unique",
            "api_key_id",
            "model_name",
            "date",
            unique=True,
        ),
    )


class ModelDailyStat(Base):
    __tablename__ = "model_daily_stats"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(100), nullable=False)
    provider_name = Column(String(50), nullable=True)
    date = Column(String(10), nullable=False)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    timeouts = Column(Integer, default=0)
    rate_limited = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_model_stats_date", "date"),
        Index(
            "idx_model_stats_unique", "model_name", "provider_name", "date", unique=True
        ),
    )


# ==================== Analysis framework ====================


class AnalysisRecord(Base):
    __tablename__ = "analysis_records"

    id = Column(Integer, primary_key=True)
    analysis_type = Column(String(50), nullable=False)
    scope_key = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    language = Column(String(10), nullable=True)
    model_used = Column(String(150), nullable=True)
    template_id = Column(String(100), nullable=True)
    template_version = Column(String(50), nullable=True)
    params_json = Column(JSONB, nullable=True)
    content = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    progress = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "idx_analysis_records_type_scope",
            "analysis_type",
            "scope_key",
            unique=True,
        ),
    )


class AnalysisSubtask(Base):
    __tablename__ = "analysis_subtasks"

    id = Column(Integer, primary_key=True)
    analysis_record_id = Column(
        Integer, ForeignKey("analysis_records.id", ondelete="CASCADE"), nullable=False
    )
    step_key = Column(String(100), nullable=False)
    step_label = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    sort_order = Column(Integer, default=0)
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=1)
    output = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "idx_analysis_subtasks_record_step",
            "analysis_record_id",
            "step_key",
            unique=True,
        ),
        Index("idx_analysis_subtasks_status", "status"),
    )


class AnalysisArtifact(Base):
    __tablename__ = "analysis_artifacts"

    id = Column(Integer, primary_key=True)
    analysis_record_id = Column(
        Integer, ForeignKey("analysis_records.id", ondelete="CASCADE"), nullable=False
    )
    subtask_id = Column(
        Integer, ForeignKey("analysis_subtasks.id", ondelete="SET NULL"), nullable=True
    )
    artifact_key = Column(String(100), nullable=False)
    artifact_type = Column(String(50), nullable=False)
    title = Column(String(150), nullable=True)
    path = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    meta = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "idx_analysis_artifacts_record_key",
            "analysis_record_id",
            "artifact_key",
            unique=True,
        ),
        Index("idx_analysis_artifacts_status", "status"),
    )


# ==================== Documents ====================


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    content = Column(Text, nullable=False, default="")
    category = Column(String(50), nullable=True)
    filename = Column(String(255), nullable=True)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_documents_slug", "slug", unique=True),
        Index("idx_documents_category", "category"),
    )


class DocumentFile(Base):
    __tablename__ = "document_files"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    filename = Column(String(255), nullable=False)
    object_name = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False)
    file_size = Column(Integer, default=0)
    content_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (Index("idx_document_files_doc_id", "document_id"),)


# ==================== Weixin bot ====================


class WeixinAccount(Base):
    __tablename__ = "weixin_accounts"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    bot_token = Column(String(512), nullable=True)
    ilink_bot_id = Column(String(128), nullable=True)
    ilink_user_id = Column(String(128), nullable=True)
    get_updates_buf = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    reply_mode = Column(String(10), default="manual")
    system_prompt = Column(Text, default="你是一个有帮助的AI助手。")
    model_name = Column(String(100), default="zhipu/glm-4-flash")
    login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class WeixinContextToken(Base):
    __tablename__ = "weixin_context_tokens"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("weixin_accounts.id"), nullable=False)
    user_id = Column(String(128), nullable=False)
    context_token = Column(Text, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_weixin_ctx_account_user", "account_id", "user_id", unique=True),
    )


class WeixinMessage(Base):
    __tablename__ = "weixin_messages"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("weixin_accounts.id"), nullable=False)
    direction = Column(String(3), nullable=False)
    from_user = Column(String(128), nullable=False)
    to_user = Column(String(128), nullable=False)
    text = Column(Text, nullable=True)
    context_token = Column(Text, nullable=True)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_weixin_msg_account", "account_id"),
        Index("idx_weixin_msg_status", "status"),
        Index("idx_weixin_msg_created", "created_at"),
    )


# ==================== MCP ====================


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    auth_type = Column(String(20), default="none")
    auth_token = Column(Text, nullable=True)
    auth_header = Column(String(100), default="Authorization")
    is_active = Column(Boolean, default=True)
    tool_prefix = Column(String(50), nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class McpCallLog(Base):
    __tablename__ = "mcp_call_logs"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    mcp_server_id = Column(Integer, ForeignKey("mcp_servers.id"), nullable=True)
    tool_name = Column(String(200), nullable=False)
    arguments = Column(JSONB, nullable=True)
    result = Column(Text, nullable=True)
    is_error = Column(Boolean, default=False)
    latency_ms = Column(Float, nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_mcp_call_logs_created_at", "created_at"),
        Index("idx_mcp_call_logs_server_id", "mcp_server_id"),
        Index("idx_mcp_call_logs_tool_name", "tool_name"),
    )


class McpCallDailyStat(Base):
    __tablename__ = "mcp_call_daily_stats"

    id = Column(Integer, primary_key=True)
    mcp_server_id = Column(Integer, ForeignKey("mcp_servers.id"), nullable=False)
    date = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=True)
    calls = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    avg_latency_ms = Column(Float, nullable=True)

    __table_args__ = (
        Index("idx_mcp_stats_date", "date"),
        Index(
            "idx_mcp_stats_unique",
            "mcp_server_id",
            "date",
            "hour",
            unique=True,
        ),
    )


# ==================== Notifications / scheduler / settings ====================


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    type = Column(String(20), nullable=False)
    level = Column(String(20), nullable=False, default="info")
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    target_api_key_id = Column(Integer, nullable=True)
    is_read_by_admin = Column(Boolean, default=False)
    read_api_key_ids = Column(JSONB, default=list)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_notifications_type", "type"),
        Index("idx_notifications_target", "target_api_key_id"),
        Index("idx_notifications_created", "created_at"),
    )


class SchedulerTask(Base):
    __tablename__ = "scheduler_tasks"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    cron_expression = Column(String(50), nullable=False)
    default_cron = Column(String(50), nullable=False)
    is_paused = Column(Boolean, default=False)
    last_run_at = Column(DateTime, nullable=True)
    last_duration_ms = Column(Integer, nullable=True)
    last_status = Column(String(20), nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SchedulerTaskLog(Base):
    __tablename__ = "scheduler_task_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_task_logs_started", "started_at"),
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_system_settings_category", "category"),
        Index("idx_system_settings_key", "key"),
    )


# ==================== RBAC ====================


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), nullable=True)
    full_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        Index("idx_user_roles_user_id", "user_id"),
        Index("idx_user_roles_role_id", "role_id"),
    )


class Menu(Base):
    __tablename__ = "menus"

    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("menus.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=True)
    icon = Column(String(50), nullable=True)
    path = Column(String(200), nullable=True)
    component = Column(String(200), nullable=True)
    permission_code = Column(String(100), nullable=True)
    sort_order = Column(Integer, default=0)
    is_visible = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    code = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    type = Column(String(20), nullable=False)  # menu, page, element, data
    resource = Column(String(50), nullable=True)
    action = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_permissions_code", "code"),
        Index("idx_permissions_resource", "resource"),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        Index("idx_role_permissions_role_id", "role_id"),
        Index("idx_role_permissions_permission_id", "permission_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(50), nullable=True)
    action = Column(String(20), nullable=False)
    resource = Column(String(50), nullable=False)
    resource_id = Column(String(100), nullable=True)
    detail = Column(Text, nullable=True)
    request_body = Column(JSONB, nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_audit_logs_created_at", "created_at"),
    )


class IpLocation(Base):
    __tablename__ = "ip_locations"

    id = Column(Integer, primary_key=True)
    ip = Column(String(64), unique=True, nullable=False)
    province = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    adcode = Column(String(20), nullable=True)
    rectangle = Column(String(200), nullable=True)
    loc = Column(String(100), nullable=True)
    country = Column(String(50), nullable=True)
    isp = Column(String(200), nullable=True)
    source = Column(String(20), default="amap")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_ip_locations_ip", "ip"),
    )
