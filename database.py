import os
import secrets
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    Index,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://api-proxy:Zaq1%403edc@192.168.58.128/api-proxy",
)

engine = create_async_engine(DATABASE_URL, echo=False)
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
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    max_tokens = Column(Integer, default=16384)
    is_multimodal = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProviderModel(Base):
    __tablename__ = "provider_models"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    model_name_override = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    provider_id = Column(Integer, nullable=True)
    model = Column(String(100), nullable=False)
    messages = Column(JSONB, nullable=True)
    response = Column(Text, nullable=True)
    tokens = Column(JSONB, nullable=True)
    latency_ms = Column(Float, nullable=True)
    status = Column(String(20), nullable=False)
    error = Column(Text, nullable=True)
    headers = Column(JSONB, nullable=True)
    request_body = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("idx_request_logs_created_at", "created_at"),
        Index("idx_request_logs_api_key_id", "api_key_id"),
    )


class ProviderDailyStat(Base):
    __tablename__ = "provider_daily_stats"

    id = Column(Integer, primary_key=True)
    provider_name = Column(String(50), nullable=False)
    date = Column(String(10), nullable=False)
    hour = Column(Integer, nullable=True)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)

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

    __table_args__ = (Index("idx_apikey_stats_date", "date"),)


class ModelDailyStat(Base):
    __tablename__ = "model_daily_stats"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(100), nullable=False)
    provider_name = Column(String(50), nullable=True)
    date = Column(String(10), nullable=False)
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    errors = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_model_stats_date", "date"),
        Index(
            "idx_model_stats_unique", "model_name", "provider_name", "date", unique=True
        ),
    )


def generate_api_key():
    return "sk-" + secrets.token_hex(24)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
