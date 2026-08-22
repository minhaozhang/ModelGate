"""Database engine, session factory and declarative base."""

import os
import secrets

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

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
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    pool_timeout=30,
    connect_args=_connect_args,
)
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


def generate_api_key():
    return "sk-" + secrets.token_hex(24)
