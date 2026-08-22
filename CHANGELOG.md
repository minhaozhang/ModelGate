# Changelog

All notable changes to ModelGate. Format based on
[Keep a Changelog](https://keepachangelog.com/). Versions are milestone-based;
dates are commit dates on the `dev` branch. Root-cause deep-dives for
May-Aug 2026 live in
[docs/CHANGELOG_2026-05_2026-08.md](docs/CHANGELOG_2026-05_2026-08.md).

## [2026-08-21] Availability Release

### Added
- Per-model context hard limit (`context_hard_limit`): over-limit requests are
  rejected at the gateway with a native `context_length_exceeded` error
  (OpenAI/Anthropic formats), letting agents auto-compact and retry instead of
  failing upstream. Admin form: Max Output / Context Window / Hard Limit.
- Auto-routing and concurrency diagnostic logging (`[AUTO ROUTING]`,
  `[KEY FALLBACK]`, `[AUTO BLOCKED]` with scoped limits).
- Request logs: User Agent column; request log detail tabs with token cache
  breakdown.

### Changed
- Model visibility now follows key permissions, not transient provider state:
  an auto-disabled (circuit-broken) or manually disabled provider no longer
  drops its models from `/v1/models` or OpenCode merge configs. Disabling a
  provider-model binding still hides the model.
- Request logs list converted to a dense table (~3x rows per screen), error
  rows highlighted, cache-hit badges.

### Fixed
- Concurrency: requests queue up to 10s for a semaphore slot instead of
  fast-failing 429 (thinking-model streams hold slots for minutes; the old 1s
  timeout made concurrent agent requests fail and exhausted opencode's retry
  budget — "agent gives up mid-session"). Queue saturation (>= 2x limit)
  still fails fast with `retry-after`.
- Model edit form: Max Output input was accidentally removed (edit button did
  nothing, `TypeError` in `editModel()`).
- OpenCode setup.ps1: inline-comment stripper ate `file:///` URLs, breaking
  JSON parse and pushing users to the destructive fresh-config path.

## [2026-08-18] GLM Health Check & Provider Availability

### Added
- Daily GLM health check at 05:30 with admin notification on failure; probe
  model configurable in system config.
- Provider availability banners (admin desktop/mobile home + user portal) with
  reason and expected restore time, polled every 30s.
- Provider-key usage breakdown on the homepage with editable key labels;
  API-key tags shown in usage panels and active sessions.

### Changed
- Auto-reenable now runs at `reset_at + 60s` instead of immediately, avoiding
  quota-window edge races (recovery flapping).

### Fixed
- GLM health check false failures on reasoning models (`max_tokens=8` was
  spent entirely on reasoning → empty content misread as dead upstream).
- Stats: aggregated-period totals were zeroed for rate_limited/errors/timeouts
  and prompt/completion split — daily stats tables now carry split columns
  with a one-time backfill; `errors` counts error-status only.
- Stats: provider key attribution crashed when a provider row was missing;
  key labels in stats now resolve from the live table instead of log snapshots.
- Dark/black-gold themes: white flash on admin page loads (early boot script
  + base-path-aware guard), near-white row hover, banner colors, mobile trend
  chart sizing, tooltips clamped to viewport/modal.

## [2026-08-05] Intent Classifier v2 & Logs Table

### Changed
- Intent classifier rewritten from 25k production logs: user-message-only
  scan, agent-protocol noise filtering, intent inheritance for short
  continuations, code-identifier detection, context negation. Validated:
  coding +16%, writing false positives -97%, chat +170% (framework noise
  correctly filtered).

### Fixed
- camelCase detection ran on lowercased text (uppercase erased → regex never
  matched); duplicate keyword broke design/coding tiebreakers.

## [2026-08-03] Performance Special

### Performance
- Dashboard stats queries switched from the 1.2GB `request_logs_all` view to
  the indexed live table; `/stats` totals from daily aggregates + today cache
  (400-500ms → 18ms warm); week totals from daily aggregates with bounded
  raw head/tail; DB pool size configurable (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`).
- Dropped redundant/zero-scan indexes (verified against pg_stat_user_indexes).

### Changed
- Database layer split into engine/models/migrations modules (no schema
  changes); legacy `api_key` column kept in sync.

### Fixed
- request_logs `created_at` server_default restored; NULL-timestamp hardening.

## [2026-07-22] Reasoning Effort & Catalog Availability

### Added
- Model `reasoning_effort` field with OpenCode `variants` support; defaults
  are provider-aware (Zhipu GLM-5.2+ maps to high/max).
- Catalog: models bound to disabled providers listed as "temporarily
  unavailable" instead of vanishing; min-price badges and pricing modals.

## [2026-07-15] Key Lifecycle

### Added
- API key regenerate/reset for admins and users.

## [2026-07-09] My Requests

### Added
- Paginated user request-history modal with filters and per-request
  context/input/output/cache/cost breakdown.

### Fixed
- Modal backdrop invisible (uncompiled Tailwind class); ORM Row attribute
  access error in the query.

## [2026-07-04] Pricing Suite

### Added
- Pricing overview with filters, batch edit, copy-across, sync, CSV export;
  user catalog min-price aggregation.

## [2026-06-27] Context-Aware Auto Routing

### Added
- Per-item `min_ctx`/`max_ctx` on the auto-routing pool; exclusions surfaced
  in route preview with reasons; quick-open terminal command on OpenCode tab.

## [2026-06-17] Routing Rework & RBAC

### Added
- Provider-less model access: API keys bind to standard models
  (`ApiKeyModelAccess`); auto virtual model access controls; API key expiry;
  provider key routing controls; RBAC (users/roles/menus/permissions, dual
  auth); audit logging for admin writes.

## [2026-06-11] Concurrency Limits

### Added
- API key global concurrency limit.

## [2026-06-01] Stability

### Fixed
- OpenCode merge endpoint 422 (body type), nginx 600s proxy timeout for long
  streams, NULL-byte cleaning on all DB write paths (asyncpg
  UntranslatableCharacterError), timezone handling for `expires_at`.

## [2026-05-28] Ops Toolkit

### Added
- Request content backup/export to gzip with cleanup; multi-dimension stats
  sub-tabs with CSV export; provider/key/model status monitoring tables.

## [2026-05-26] V2 Foundation

### Added
- Provider key health scoring (sliding window) with health-ordered key
  selection; model alias/tags/routing; intent classification
  (coding/writing/testing/design/chat); request content separated into
  `request_contents` with lazy loading; auto-disable provider keys on auth
  errors; audit logging; RBAC backend.

### Removed
- Legacy AI error-analysis module (routes, page, helpers).

## [2026-05-21] Baseline

Multi-provider LLM gateway: OpenAI/Anthropic-compatible proxy, API key
management, request logging, dashboards, MCP proxy, WeChat iLink Bot, MinIO,
i18n.
