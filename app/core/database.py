import os
import secrets
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    Date,
    Time,
    Index,
    ForeignKey,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, registry
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://modelgate:change_me@localhost:5432/modelgate",
)

_search_path = os.getenv("DB_SEARCH_PATH")
_connect_args = {}
if _search_path:
    _connect_args["server_settings"] = {"search_path": _search_path}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    connect_args=_connect_args,
)
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


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
    action = Column(String(20), nullable=False, default="prefer")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_provider_model_routing_rules_pm", "provider_model_id"),
    )


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    max_tokens = Column(Integer, default=131072)
    context_length = Column(Integer, default=204800)
    thinking_enabled = Column(Boolean, default=True)
    thinking_budget = Column(Integer, default=8192)
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
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_provider_model", "provider_id", "model_id", unique=True),
    )


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
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_request_logs_created_at", "created_at"),
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
    created_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=True)
    archive_month = Column(String(7), nullable=False)
    archived_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_request_logs_history_created_at", "created_at"),
        Index("idx_request_logs_history_api_key_id", "api_key_id"),
        Index("idx_request_logs_history_provider_id", "provider_id"),
        Index("idx_request_logs_history_status", "status"),
        Index("idx_request_logs_history_archive_month", "archive_month"),
    )


read_registry = registry()
request_logs_all_table = read_registry.metadata.tables.get("request_logs_all")
if request_logs_all_table is None:
    from sqlalchemy import Table

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


class ProviderDailyStat(Base):
    __tablename__ = "provider_daily_stats"

    id = Column(Integer, primary_key=True)
    provider_name = Column(String(50), nullable=False)
    date = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=True)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)
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
    errors = Column(Integer, default=0)
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
    errors = Column(Integer, default=0)
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
    errors = Column(Integer, default=0)
    rate_limited = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_model_stats_date", "date"),
        Index(
            "idx_model_stats_unique", "model_name", "provider_name", "date", unique=True
        ),
    )


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
        Index("idx_analysis_records_status", "status"),
        Index("idx_analysis_records_expires_at", "expires_at"),
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
        Index("idx_task_logs_task", "task_id"),
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


def generate_api_key():
    return "sk-" + secrets.token_hex(24)


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
        await conn.execute(
            text(
                "ALTER TABLE models "
                "ADD COLUMN IF NOT EXISTS thinking_enabled BOOLEAN DEFAULT TRUE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE models "
                "ADD COLUMN IF NOT EXISTS thinking_budget INTEGER DEFAULT 8192"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE models "
                "ADD COLUMN IF NOT EXISTS estimated_price FLOAT DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE models "
                "ADD COLUMN IF NOT EXISTS is_virtual BOOLEAN DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS upstream_status_code INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS downstream_status_code INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs_history "
                "ADD COLUMN IF NOT EXISTS upstream_status_code INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs_history "
                "ADD COLUMN IF NOT EXISTS downstream_status_code INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS user_agent VARCHAR(1024)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS request_context_tokens INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS inbound_protocol VARCHAR(20)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE request_logs_history "
                "ADD COLUMN IF NOT EXISTS inbound_protocol VARCHAR(20)"
            )
        )
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS intent VARCHAR(20)"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS intent VARCHAR(20)"))
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS requested_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS actual_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS provider_key_id INTEGER"))
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS provider_key_label VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS routing_decision JSONB"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS requested_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS actual_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS provider_key_id INTEGER"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS provider_key_label VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS routing_decision JSONB"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS archive_month VARCHAR(7)"))
        await conn.execute(text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP DEFAULT now()"))
        await conn.execute(text("UPDATE request_logs_history SET archive_month = to_char(created_at, 'YYYY-MM') WHERE archive_month IS NULL"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_request_logs_history_id ON request_logs_history (id)"))
        await conn.execute(
            text(
                "ALTER TABLE provider_daily_stats "
                "ADD COLUMN IF NOT EXISTS rate_limited INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE api_key_daily_stats "
                "ADD COLUMN IF NOT EXISTS rate_limited INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE api_key_model_daily_stats "
                "ADD COLUMN IF NOT EXISTS rate_limited INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE model_daily_stats "
                "ADD COLUMN IF NOT EXISTS rate_limited INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP")
        )
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
        )
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP")
        )
        await conn.execute(
            text("UPDATE api_keys SET expires_at = now() + interval '1 year' WHERE expires_at IS NULL")
        )
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS bypass_busyness BOOLEAN DEFAULT FALSE")
        )
        await conn.execute(
            text(
                "ALTER TABLE providers ADD COLUMN IF NOT EXISTS disabled_reason VARCHAR(255)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE providers ADD COLUMN IF NOT EXISTS protocol VARCHAR(20) DEFAULT 'openai'"
            )
        )
        await conn.execute(
            text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP")
        )
        await conn.execute(
            text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMP")
        )
        await conn.execute(
            text("ALTER TABLE providers ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP")
        )
        await conn.execute(
            text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP")
        )
        await conn.execute(
            text(
                "UPDATE providers SET protocol = 'openai' WHERE protocol IS NULL OR protocol = ''"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE weixin_accounts "
                "ADD COLUMN IF NOT EXISTS api_key_id INTEGER REFERENCES api_keys(id)"
            )
        )
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
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS file_object_name VARCHAR(500)"
            )
        )
        await conn.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_type VARCHAR(20)")
        )
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
        for table_name in ("request_logs", "request_logs_history"):
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS request_context_tokens INTEGER"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS upstream_status_code INTEGER"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS downstream_status_code INTEGER"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64)"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS user_agent VARCHAR(1024)"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS inbound_protocol VARCHAR(20)"
                )
            )
            await conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS error TEXT")
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS intent VARCHAR(20)"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS requested_model VARCHAR(100)"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS actual_model VARCHAR(100)"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS provider_key_id INTEGER"
                )
            )
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN IF NOT EXISTS provider_key_label VARCHAR(50)"
                )
            )
        await conn.execute(text("DROP VIEW IF EXISTS request_logs_all"))
        await conn.execute(
            text(
                "CREATE VIEW request_logs_all AS "
                "SELECT id, api_key_id, provider_id, model, response, tokens, latency_ms, "
                "request_context_tokens, status, upstream_status_code, downstream_status_code, client_ip, user_agent, "
                "inbound_protocol, error, intent, requested_model, actual_model, provider_key_id, provider_key_label, routing_decision, created_at, updated_at "
                "FROM request_logs "
                "UNION ALL "
                "SELECT id, api_key_id, provider_id, model, response, tokens, latency_ms, "
                "request_context_tokens, status, upstream_status_code, downstream_status_code, client_ip, user_agent, "
                "inbound_protocol, error, intent, requested_model, actual_model, provider_key_id, provider_key_label, routing_decision, created_at, updated_at "
                "FROM request_logs_history"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE analysis_records "
                "ADD COLUMN IF NOT EXISTS progress VARCHAR(200)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE analysis_records "
                "ADD COLUMN IF NOT EXISTS template_id VARCHAR(100)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE analysis_records "
                "ADD COLUMN IF NOT EXISTS template_version VARCHAR(50)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE analysis_records "
                "ADD COLUMN IF NOT EXISTS params_json JSONB"
            )
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
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ak_mcp_unique ON api_key_mcp_servers (api_key_id, mcp_server_id)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mcp_servers DROP COLUMN IF EXISTS api_key_id"
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
            text(
                "CREATE INDEX IF NOT EXISTS idx_mcp_stats_date "
                "ON mcp_call_daily_stats (date)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_stats_unique "
                "ON mcp_call_daily_stats (mcp_server_id, date, hour)"
            )
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
            text(
                "ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS max_concurrent INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS cost_role VARCHAR(40) DEFAULT 'standard'"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_provider_keys_provider ON provider_keys (provider_id)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE providers DROP COLUMN IF EXISTS max_concurrent"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE provider_models DROP COLUMN IF EXISTS max_concurrent"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO provider_keys (provider_id, api_key, label, is_active) "
                "SELECT id, api_key, 'default', TRUE "
                "FROM providers "
                "WHERE api_key IS NOT NULL AND api_key != '' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM provider_keys pk WHERE pk.provider_id = providers.id AND pk.api_key = providers.api_key"
                ")"
            )
        )
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
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs (user_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs (resource)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs (action)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at)"
            )
        )
        await conn.execute(
            text("ALTER TABLE models ADD COLUMN IF NOT EXISTS tags TEXT")
        )
        await conn.execute(
            text("ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS alias VARCHAR(100)")
        )
        await conn.execute(
            text(
                "ALTER TABLE provider_models "
                "ADD COLUMN IF NOT EXISTS max_busyness_level INTEGER"
            )
        )
        await conn.execute(
            text("ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS upstream_model_name VARCHAR(100)")
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
            text("ALTER TABLE provider_models ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0")
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
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS intent VARCHAR(20)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS intent VARCHAR(20)")
        )
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS preferred_tags TEXT")
        )
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS requested_model VARCHAR(100)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS actual_model VARCHAR(100)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS provider_key_id INTEGER")
        )
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS provider_key_label VARCHAR(50)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS routing_decision JSONB")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS requested_model VARCHAR(100)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS actual_model VARCHAR(100)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS provider_key_id INTEGER")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS provider_key_label VARCHAR(50)")
        )
        await conn.execute(
            text("ALTER TABLE request_logs_history ADD COLUMN IF NOT EXISTS routing_decision JSONB")
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
        await conn.execute(
            text("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0")
        )
        await conn.execute(
            text(
                "ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS cost_role VARCHAR(40) DEFAULT 'standard'"
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
                "action VARCHAR(20) NOT NULL DEFAULT 'prefer', "
                "created_at TIMESTAMP DEFAULT NOW()"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_provider_model_routing_rules_pm "
                "ON provider_model_routing_rules (provider_model_id)"
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
                "config_schema = EXCLUDED.config_schema, "
                "rule_blueprint = EXCLUDED.rule_blueprint, "
                "updated_at = NOW()"
            )
        )
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
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_request_contents_log_id ON request_contents (log_id)"
            )
        )


# ==================== RBAC Models ====================

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
        Index("idx_audit_logs_user_id", "user_id"),
        Index("idx_audit_logs_resource", "resource"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_created_at", "created_at"),
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
