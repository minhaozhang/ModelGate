# Product

## Register

product

## Users

Two distinct audiences:

1. **Operations administrators** manage LLM providers, API keys, monitor system health (busyness levels, concurrency, error rates), generate usage reports, and configure scheduled tasks. They work in dim monitoring rooms or office environments, often with multiple tabs open, needing at-a-glance status clarity.

2. **Developers** use API keys to route requests through the gateway, check personal usage stats, discover available models, and configure client integrations (OpenCode, MCP). They visit the dashboard briefly between coding sessions, needing fast answers with minimal friction.

## Product Purpose

ModelGate is a unified LLM intelligent routing gateway that sits between client applications and multiple LLM providers. It provides OpenAI-compatible API endpoints, multi-provider routing with layered concurrency control, busyness-based availability management, per-key model access control, and operational monitoring. Success means: administrators can confidently manage and monitor the gateway at a glance, and developers can discover and use models without friction.

## Brand Personality

Reliable, efficient, professional.

The interface should feel like a well-built control panel: precise, trustworthy, never flashy. Every element earns its place. Information density is high but never cluttered. Trust is built through consistency and clarity, not decoration.

## Anti-references

- **One API / New API**: Open-source LLM gateway panels with visually rough, template-like interfaces. ModelGate must not look like a generic admin template or a quickly-assembled dashboard.
- **Generic SaaS admin templates**: Cookie-cutter layouts with identical card grids, hero metrics, and gradient accents. ModelGate should feel purpose-built, not like a Bootstrap theme.

## Design Principles

1. **Signal over noise**: Every pixel should convey meaningful information. Remove decorative elements that don't serve comprehension or action.
2. **At-a-glance clarity**: Administrators monitoring the gateway should understand system state in under 3 seconds. Hierarchy and visual weight must reflect operational priority.
3. **Precision craftsmanship**: Consistent spacing, alignment, and typography. Details matter because reliability is the brand. Rough edges undermine trust.
4. **Developer fluency**: Speak the language of developers: monospace where appropriate, clear status codes, concise labels. No hand-holding, no verbose onboarding.
5. **Density with breathing room**: Pack information efficiently, but use intentional whitespace to separate concerns. Cramped is stressful; sparse is wasteful.

## Accessibility & Inclusion

WCAG AAA compliance. High contrast ratios (7:1 minimum for normal text), clear focus indicators, keyboard navigable, screen reader friendly. Support reduced motion preferences. Ensure status is never conveyed by color alone.
