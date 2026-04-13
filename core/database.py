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
    "postgresql+asyncpg://modelgate:Zaq1%403edc@192.168.58.128/modelgate",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
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
    max_concurrent = Column(Integer, default=3)
    merge_consecutive_messages = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    max_tokens = Column(Integer, default=16384)
    context_length = Column(Integer, default=131072)
    thinking_enabled = Column(Boolean, default=True)
    thinking_budget = Column(Integer, default=8192)
    is_multimodal = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ProviderModel(Base):
    __tablename__ = "provider_models"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_name_override = Column(String(100), nullable=True)
    max_concurrent = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
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


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    key = Column(String(64), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


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
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    error = Column(Text, nullable=True)
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
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    error = Column(Text, nullable=True)
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
        Column("client_ip", String(64)),
        Column("user_agent", String(1024)),
        Column("error", Text),
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


def generate_api_key():
    return "sk-" + secrets.token_hex(24)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
                "ALTER TABLE request_logs "
                "ADD COLUMN IF NOT EXISTS upstream_status_code INTEGER"
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
                "CREATE OR REPLACE VIEW request_logs_all AS "
                "SELECT id, api_key_id, provider_id, model, response, tokens, latency_ms, "
                "request_context_tokens, status, upstream_status_code, client_ip, user_agent, "
                "error, created_at, updated_at "
                "FROM request_logs "
                "UNION ALL "
                "SELECT id, api_key_id, provider_id, model, response, tokens, latency_ms, "
                "request_context_tokens, status, upstream_status_code, client_ip, user_agent, "
                "error, created_at, updated_at "
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
