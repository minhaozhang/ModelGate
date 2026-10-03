# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two confirmed audiences, both first-class:

1. **Gateway operators (admins)** — the people who run a ModelGate deployment: configure providers/keys/pricing, watch live health, manage users and audit. They work in the admin console daily and value ops density: monitoring, diagnosis, and fast corrective action.
2. **API consumers (end users, mostly developers and coding agents)** — hold personal API keys, call OpenAI/Anthropic-compatible endpoints, check their own usage/stats/health in the user portal, and bootstrap clients (OpenCode one-liner setup, config export).

The product serves **both internal operation and external adoption equally** (confirmed): deployments like leturx.cc run it for a real team, and new organizations self-hosting it for the first time must also succeed. Neither onboarding nor daily-ops density may be sacrificed for the other.

## Product Purpose

ModelGate is a self-hosted LLM gateway: multi-provider routing, API key management, request logging, and monitoring behind OpenAI-compatible (`/v1/chat/completions`, `/v1/embeddings`, `/v1/models`) and Anthropic-compatible (`/anthropic/v1/messages`, full protocol translation) endpoints. It exists so a team centralizes and distributes AI model access across departments with control (per-key access, quotas, time rules), observability (per-request logging, stats, health scoring), and resilience (fallback, concurrency queuing) that direct provider accounts cannot give.

Success means: callers use one stable endpoint and standard model names regardless of which providers are configured underneath; operators see and fix problems before users notice; a new team can deploy and be productive in one sitting.

## Positioning

Confirmed differentiating mechanism versus neighboring gateways (one-api / new-api / LiteLLM):

- **Provider-less standard model access** — API keys bind to standard models directly; callers address models by name, alias, or `provider/model` for explicit routing, instead of provider-shaped endpoints.
- **The `auto` virtual model** — a context-window-aware model pool (per-item min_ctx/max_ctx) with automatic provider selection, fallback on 5xx/network errors, and route preview with exclusion reasons.

Supporting mechanics that reinforce the position: layered concurrency control with up-to-10s slot queuing (429 only when the wait queue saturates), sliding-window provider-key health scores feeding routing priority, intent classification (coding/writing/testing/design/chat) for smart routing and analytics, and deep OpenCode integration (one-liner setup, per-model context/output limits, reasoning-effort variants).

## Operating Context

- Self-hosted via Docker Compose (Nginx reverse proxy, static file serving, internal registry); production reference deployment at `https://leturx.cc/modelgate` under a configurable base path.
- Two portals: admin console (monitor with a five-dial Porsche-binnacle instrument cluster, providers, models, keys, pricing, users/RBAC, logs, audit) and user portal (dashboard, personal stats, request history, documents, client setup guides).
- Heavy daily-driver surfaces are the admin monitor and the user dashboard/stats; coding agents (OpenCode, Claude Code) are first-class downstream clients, so native `context_length_exceeded` semantics (agents auto-compact and retry) are part of the contract.
- Ops rituals: docker build/push to an internal registry release flow; pytest with a known pre-existing failure baseline; visual changes verified by screenshot + vision-model review before release.

## Capabilities and Constraints

Confirmed constraints future work must preserve:

- **Bilingual parity**: all user-visible copy ships zh + en via Babel (.po compiled); Chinese is the primary authoring language.
- **Tri-theme parity**: light / dark / black-gold themes are all supported on desktop and mobile web; new UI must hold up in all three.
- **Localized static assets**: no CDN dependencies anywhere.
- **Reduced-motion**: all animation must adapt to `prefers-reduced-motion` (see Accessibility).
- Reverse-proxy friendly (configurable base path); PostgreSQL + asyncpg; MinIO for file storage.
- Terminology: "provider" = upstream vendor account with its own keys; "model" = standard model registry entry; "key" = end-user API key unless qualified as provider key.

## Brand Commitments

- Name: **ModelGate**; logo at `web/assets/favicon.svg`.
- Voice: concise, ops-flavored UI copy; no marketing fluff inside the product.
- Established visual signatures the user has treated as binding: the black-gold theme, and the Porsche-binnacle instrument language on monitoring surfaces (dark dial faces, bezel rings, spring-physics needles, redline zones).

## Evidence on Hand

- README (`README.md`) with full capability list and screenshots under `image/` (admin dashboard, admin monitor, user dashboard).
- Live reference deployment `https://leturx.cc/modelgate` and a seeded repro environment for verification.
- No testimonials, case studies, or external press on hand — future copy must not fabricate any.

## Product Principles

1. **One stable face to callers** — endpoint and model-name stability outranks provider-side convenience; callers should never feel provider churn.
2. **Operate first, but welcome like a product** — ops surfaces optimize for scan-and-act density; first-run and client-setup flows still get product-grade care, because external adoption is equally weighted.
3. **Degrade loudly and recover automatically** — fallbacks, queues, and health scores exist so failures surface as native, actionable signals (retry-after, context errors) rather than silent breakage.
4. **Every visible state earns its pixels** — monitoring UI favors real instrument semantics (gauge range = effective capacity, redline = real threshold) over decoration; data-encoding integrity is verified, not assumed.
5. **Bilingual and theme-complete by default** — a feature is not done until it reads right in zh and en and renders right in all three themes with reduced-motion honored.

## Accessibility & Inclusion

- **`prefers-reduced-motion` is a binding requirement** (confirmed in practice across sessions): every animation must offer a reduced-motion path (OS-level setting; users with vestibular sensitivity rely on it — non-essential motion is removed or replaced with instant state changes).
- Dark-first readability on monitoring surfaces: gauge dials stay dark in all themes by design; text contrast on the dark pods is part of the craft floor.
