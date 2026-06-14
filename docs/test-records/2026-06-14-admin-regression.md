# 2026-06-14 Admin Regression Record

Environment:
- Local URL: http://localhost:8766/modelgate
- Database: 116.198.230.210:8866/api_proxy, schema public
- Admin test user: codex_test_admin
- Password change test user: codex_pw_test

Browser pages checked:
- /admin/home
- /admin/config?tab=overview
- /admin/config?tab=providers
- /admin/config?tab=models
- /admin/config?tab=routing
- /admin/config?tab=templates
- /admin/config?tab=preview
- /admin/api-keys
- /admin/monitor
- /admin/reports
- /admin/documents
- /admin/mcp-servers
- /admin/request-logs
- /admin/users
- /admin/roles
- /admin/audit
- /admin/notifications
- /admin/scheduler-tasks
- /admin/system-config

Key browser interactions checked:
- Admin login and authenticated navigation.
- Config tab highlighting and direct tab URLs.
- Route preview for glm-5.1 with 2000 context tokens.
- Provider Key drawer from provider config.
- API Key list loading, copy button, and clipboard prefix.
- Request logs query view.
- Users page data, including codex_test_admin.
- Roles page data and permissions.
- System config load.
- Scheduler tasks and logs load.

API checks:
- Providers, models, provider-models, routing templates, routing resolve.
- API keys, documents, MCP servers.
- RBAC users, roles, permissions.
- Stats period/active/busyness/chart/slow/aggregate/monitor-details.
- Provider-model status and system info.
- MCP logs, request logs query/aggregate.
- Audit resources/logs.
- Usage report template/history.
- System config/UA stats.
- Scheduler tasks/logs.

Issues found and fixed:
- API Key page showed `0 keys` while data was still loading. It now starts with `... keys`, loads independently from model selector initialization, and displays an explicit error if key loading fails.
- Change password success path referenced undefined `sql_update`; it now uses SQLAlchemy `update`.

Persistent test records kept:
- `codex_test_admin` remains in RBAC users.
- `codex_pw_test` remains in RBAC users after successful password-change verification.
