"""Compatibility facade for the database layer.

All engine/session/model/migration imports across the codebase go through
this module. Actual definitions live in:

- app.core.db_engine     engine, session factory, Base, generate_api_key
- app.core.db_models     ORM models + read-only view mapping
- app.core.db_migrations init_db() startup migrations and seed data
"""

from app.core.db_engine import (  # noqa: F401
    DATABASE_URL,
    Base,
    async_session_maker,
    engine,
    generate_api_key,
)
from app.core.db_models import (  # noqa: F401
    AnalysisArtifact,
    AnalysisRecord,
    AnalysisSubtask,
    ApiKey,
    ApiKeyDailyStat,
    ApiKeyMcpServer,
    ApiKeyModel,
    ApiKeyModelAccess,
    ApiKeyModelDailyStat,
    ApiKeyTag,
    ApiKeyTimeRule,
    AuditLog,
    AutoModelRoute,
    Document,
    DocumentFile,
    IpLocation,
    McpCallDailyStat,
    McpCallLog,
    McpServer,
    Menu,
    Model,
    ModelDailyStat,
    Notification,
    Permission,
    Provider,
    ProviderDailyStat,
    ProviderKey,
    ProviderKeyRoutingRule,
    ProviderKeyStrategyAssignment,
    ProviderKeyStrategyTemplate,
    ProviderModel,
    ProviderModelRoutingRule,
    RequestContent,
    RequestLog,
    RequestLogHistory,
    RequestLogRead,
    Role,
    RolePermission,
    SchedulerTask,
    SchedulerTaskLog,
    SystemSetting,
    User,
    UserRole,
    WeixinAccount,
    WeixinContextToken,
    WeixinMessage,
    read_registry,
)
from app.core.db_migrations import (  # noqa: F401
    default_rbac_permissions,
    default_rbac_roles,
    init_db,
    seed_rbac_defaults,
)
