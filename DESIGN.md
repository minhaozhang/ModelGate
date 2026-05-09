---
name: ModelGate
description: LLM intelligent routing gateway for developers
colors:
  primary: "#0e7490"
  primary-light: "#22d3ee"
  primary-dark: "#155e75"
  neutral-bg: "#f8fafb"
  neutral-surface: "#ffffff"
  neutral-border: "#e2e8f0"
  dark-bg: "#0c1222"
  dark-surface: "#111a2e"
  dark-border: "#1e2d4a"
  dark-elevated: "#162033"
  success: "#059669"
  error: "#dc2626"
  warning: "#d97706"
  info: "#0284c7"
typography:
  display:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.2
  headline:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.3
  title:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "system-ui, -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.025em"
  mono:
    fontFamily: "'SF Mono', 'Cascadia Code', 'Consolas', monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  xl: "16px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-dark}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  input-default:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "#1e293b"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  nav-link-active:
    backgroundColor: "rgba(14, 116, 144, 0.08)"
    textColor: "{colors.primary}"
  badge-success:
    backgroundColor: "rgba(5, 150, 105, 0.1)"
    textColor: "{colors.success}"
    rounded: "{rounded.sm}"
  badge-error:
    backgroundColor: "rgba(220, 38, 38, 0.1)"
    textColor: "{colors.error}"
    rounded: "{rounded.sm}"
---

# Design System: ModelGate

## 1. Overview

**Creative North Star: "The Engineer's Bench / The Command Center"**

ModelGate serves two distinct surfaces, each with its own North Star. The admin portal is a command center: operators monitoring gateway health at a glance, making decisions under time pressure. The user portal is an engineer's bench: developers checking stats and configuring clients between coding sessions, needing fast answers with minimal friction.

Both surfaces share a single visual foundation: flat, information-dense, and deliberate. Every element earns its place. The system rejects decoration that doesn't serve comprehension or action. Depth is conveyed through tonal layering, not shadow; surfaces are flat at rest and respond with subtle elevation on interaction.

This system explicitly rejects the visual language of One API and generic SaaS admin templates: no hero-metric layouts with gradient accents, no identical card grids, no glassmorphism as default, no side-stripe borders. ModelGate feels purpose-built, not assembled from a template.

**Key Characteristics:**
- Flat by default, responsive on interaction
- Tonal layering over shadow for depth
- Information density with intentional breathing room
- Monospace for code, data, and identifiers
- Status conveyed through shape and position, never color alone

## 2. Colors

The palette is anchored in cool teal-gray, avoiding the default Tailwind blue that signals "generic SaaS tool." Primary accents are restrained, used on interactive elements and active states only. Most of the surface is neutral territory.

**The Restrained Accent Rule.** The primary accent appears on no more than 10% of any given screen. Its rarity is the point: it draws the eye precisely to interactive elements and active states, never to decoration.

### Primary
- **Deep Teal** (#0e7490): Primary interactive elements, buttons, active nav links, focus rings. Used sparingly; most of the surface is neutral.
- **Cyan Highlight** (#22d3ee): Hover states on primary elements, light accent in charts. Never used for large fills.
- **Dark Teal** (#155e75): Pressed/active state for primary buttons.

### Neutral (Light)
- **Cloud White** (#f8fafb): Page background. Slightly cooler than pure white, tinted toward the teal axis.
- **Surface White** (#ffffff): Card and panel backgrounds.
- **Frost Border** (#e2e8f0): Dividers, input borders, card outlines.

### Neutral (Dark)
- **Midnight** (#0c1222): Dark mode page background. Deep blue-black, not pure black.
- **Dark Surface** (#111a2e): Dark mode cards and panels.
- **Dark Border** (#1e2d4a): Dark mode dividers and outlines.
- **Dark Elevated** (#162033): Dark mode elevated surfaces (modals, dropdowns).

### Semantic
- **Success** (#059669): Confirmations, healthy status, positive metrics.
- **Error** (#dc2626): Failures, critical alerts, disabled providers.
- **Warning** (#d97706): Caution states, busyness warnings.
- **Info** (#0284c7): Informational badges, neutral status.

## 3. Typography

**Display Font:** system-ui, -apple-system, sans-serif
**Body Font:** system-ui, -apple-system, sans-serif
**Mono Font:** SF Mono, Cascadia Code, Consolas, monospace

**Character:** One family doing all the work. Weight and scale create hierarchy, not font pairings. The system font is fast, legible, and familiar. Monospace appears for code, API keys, model identifiers, and data values where character alignment matters.

### Hierarchy
- **Display** (700, 1.875rem/30px, 1.2): Page titles. Used once per page.
- **Headline** (600, 1.25rem/20px, 1.3): Section headers, modal titles.
- **Title** (600, 1rem/16px, 1.4): Card headers, list item titles, form labels.
- **Body** (400, 0.875rem/14px, 1.6): Paragraph text, descriptions, table content. Max line length 65ch.
- **Label** (500, 0.75rem/12px, 0.025em): Badges, metadata, timestamps, tab labels.
- **Mono** (400, 0.8125rem/13px, 1.5): API keys, model names, code snippets, numeric data.

**The Mono-for-Data Rule.** Any value that a developer might copy, compare, or grep should be in the mono font: API keys, model identifiers, token counts, error codes, request IDs.

## 4. Elevation

**Flat by default, responsive on interaction.** The system uses tonal layering to separate surfaces, not shadows. Background color shifts (white vs. cloud-white vs. gray-50) establish visual hierarchy without implying physical depth.

Shadows appear only as a response to interaction: hover on interactive cards, focus on inputs, and open modals/dropdowns. Even then, shadows are ambient and diffuse, not sharp or dramatic.

**The Flat-By-Default Rule.** Surfaces are flat at rest. Shadows appear only as a response to state (hover, focus, elevation). If a shadow is visible without interaction, it's too much.

### Shadow Vocabulary
- **Rest**: none. Cards and panels are separated by background color contrast alone.
- **Hover** (`0 2px 8px rgba(0,0,0,0.08)`): Subtle lift on interactive cards and list items.
- **Focus** (`0 0 0 2px rgba(14, 116, 144, 0.3)`): Teal ring on focused inputs and buttons.
- **Elevated** (`0 8px 24px rgba(0,0,0,0.12)`): Modals, dropdowns, and floating panels.

### Dark Mode Elevation
In dark mode, elevation uses lighter surface colors instead of shadows: `#0c1222` (base) → `#111a2e` (surface) → `#162033` (elevated). Shadows are darker and more diffuse: `0 8px 24px rgba(0,0,0,0.4)`.

## 5. Components

### Buttons
- **Shape:** Gently rounded (8px radius), compact padding (8px 16px).
- **Primary:** Deep Teal background, white text. No border.
- **Hover / Focus:** Dark Teal on hover. Teal focus ring on focus.
- **Ghost / Secondary:** Transparent background, Deep Teal text. Teal border on hover.
- **Danger:** Error red background for destructive actions.

### Chips / Badges
- **Shape:** Small rounded (4px) for badges, pill (9999px) for chips/tags.
- **Semantic badges:** Tinted background at 10% opacity, semantic text color. No border.
- **Model chips:** Teal-tinted background, teal text, thin teal border. In dark mode, reduced opacity.

### Cards / Containers
- **Corner Style:** Gently rounded (8px for compact, 12px for prominent).
- **Background:** Surface White on Cloud White page. In dark mode: Dark Surface on Midnight.
- **Shadow Strategy:** Flat at rest. Hover shadow on interactive cards only.
- **Border:** 1px Frost Border in light mode, 1px Dark Border in dark mode.
- **Internal Padding:** 16px (md) for standard cards, 20px for stat cards.

### Inputs / Fields
- **Style:** 1px Frost Border, Surface White background, 8px radius.
- **Focus:** Teal ring (2px offset), border shifts to Deep Teal.
- **Dark Mode:** Dark Surface background, Dark Border, lighter text.

### Navigation (Admin Sidebar)
- **Style:** Fixed 224px sidebar, Surface White background, 1px right border.
- **Links:** Body weight, gray-700 text. Active: Deep Teal text, teal-tinted background, 3px right border in teal.
- **Hover:** Subtle teal-tinted background.
- **Dark Mode:** Dark Surface background, lighter text, cyan-tinted active state.

### Navigation (User Tabs)
- **Style:** Horizontal tab strip. Body weight, gray-500 text. Active: Deep Teal text, 2px bottom border in teal.
- **Hover:** Text shifts darker.

### Stat Cards (Dashboard)
- **Layout:** Compact metric display: label above, large number below.
- **Number:** Display weight, 1.875rem, mono font for numeric values.
- **Color Coding:** Semantic colors for the metric value (teal for primary, green for tokens, orange for active, red for errors). Never the container, always the value.

### Toast Notifications
- **Position:** Top-right, fixed.
- **Style:** Compact bar, semantic background tint, close button.
- **Duration:** Auto-dismiss after 3 seconds.

## 6. Do's and Don'ts

### Do:
- **Do** use tonal layering (background color shifts) to separate surfaces instead of shadows.
- **Do** use the mono font for any value a developer might copy or compare: API keys, model names, token counts, request IDs.
- **Do** convey status through shape, position, and text, never color alone. A red badge must also say "Error" or show an icon.
- **Do** keep the primary accent to under 10% of any screen surface.
- **Do** use semantic colors only on the data value itself (metric number, badge text), not the container.
- **Do** ensure 7:1 contrast ratio for all body text (WCAG AAA).
- **Do** respect `prefers-reduced-motion`: disable flip-digit and session animations.

### Don't:
- **Don't** use the default Tailwind blue (#3b82f6) as primary. It signals "generic SaaS tool," the exact anti-reference from PRODUCT.md.
- **Don't** look like One API or New API. No rough, template-like panels. No visual sloppiness that undermines trust.
- **Don't** use identical card grids with icon + heading + text repeated endlessly.
- **Don't** use gradient text (`background-clip: text`). Emphasis through weight or size.
- **Don't** use side-stripe borders (`border-left` or `border-right` greater than 1px) as colored accents on cards or list items.
- **Don't** use glassmorphism (backdrop-filter: blur) on admin or dashboard surfaces. It's reserved for the public landing page only.
- **Don't** use hero-metric templates (big number, small label, gradient accent, supporting stats). That's a SaaS cliche.
- **Don't** add shadows to resting surfaces. Shadows are for interaction response only.
- **Don't** use em dashes in UI copy. Use commas, colons, or periods.
- **Don't** copy-paste dark-mode overrides per template. Use shared CSS custom properties.
