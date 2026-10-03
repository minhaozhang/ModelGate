---
name: ModelGate
description: Self-hosted LLM gateway — one stable OpenAI/Anthropic-compatible face for every provider underneath.
colors:
  signal-green: "#22c55e"
  signal-green-bright: "#4ade80"
  aged-brass: "#d4a853"
  brass-muted: "#c9b896"
  action-blue: "#3b82f6"
  action-blue-deep: "#2563eb"
  indigo-focus: "#818cf8"
  violet-active: "#a78bfa"
  redline: "#ef4444"
  telltale-amber: "#f59e0b"
  telltale-green: "#10b981"
  cockpit-night: "#050508"
  night-panel: "#0a0a12"
  night-raised: "#14141f"
  night-text: "#ededf8"
  zinc-abyss: "#09090b"
  brass-panel: "#1a1814"
  paper: "#ffffff"
  porcelain: "#f3f4f6"
  gauge-bezel: "#9aa4b2"
typography:
  display:
    fontFamily: "'Instrument Sans', system-ui, -apple-system, sans-serif"
    fontSize: "clamp(44px, 7vw, 84px)"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.06em"
  dial:
    fontFamily: "'Lucida Console', Menlo, Monaco, 'Courier New', monospace"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.2
rounded:
  control: "4px"
  control-md: "6px"
  card: "8px"
  tab: "10px"
  panel: "12px"
  tabbar: "14px"
  modal: "16px"
  cluster: "18px"
  pill: "9999px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "20px"
  xl: "24px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.action-blue}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "8px 24px"
  button-primary-hover:
    backgroundColor: "{colors.action-blue-deep}"
  button-landing:
    backgroundColor: "{colors.signal-green}"
    textColor: "{colors.zinc-abyss}"
    rounded: "{rounded.card}"
    padding: "11px 22px"
  button-landing-hover:
    backgroundColor: "{colors.signal-green-bright}"
  button-ghost:
    backgroundColor: "{colors.paper}"
    textColor: "#4b5563"
    rounded: "{rounded.card}"
    padding: "6px 12px"
  card-light:
    backgroundColor: "{colors.paper}"
    textColor: "#1f2937"
    rounded: "{rounded.card}"
    padding: "20px"
  card-dark:
    backgroundColor: "rgba(235, 234, 250, 0.03)"
    textColor: "{colors.night-text}"
    rounded: "{rounded.modal}"
    padding: "20px"
  card-brass:
    backgroundColor: "{colors.brass-panel}"
    textColor: "#fafaf9"
    rounded: "{rounded.modal}"
    padding: "20px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "#374151"
    rounded: "{rounded.card}"
    padding: "6px 10px"
  badge-health:
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  tab-active:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.action-blue-deep}"
    rounded: "{rounded.tab}"
    padding: "8px 16px"
  nav-link-active:
    backgroundColor: "rgba(59, 130, 246, 0.10)"
    textColor: "{colors.action-blue}"
    padding: "12px 16px"
    width: "224px"
---

# Design System: ModelGate

## Overview

**Creative North Star: "The Driver's Cockpit"**

ModelGate is the instrument panel of a car you drive every day, not a brochure about one. The whole visual system orbits one signature: the Porsche-binnacle instrument cluster on the monitoring surfaces — dark dial faces, metal bezel rings, spring-physics needles, redline zones that mark real thresholds, tell-tale lamps that light when something is wrong. Everything else in the product is built to keep the driver reading and acting at speed: dense metric grids, quiet cards, restrained controls. Density is a feature, not a defect; every visible state earns its pixels, and gauge ranges always equal real capacity.

The mood is instrument-grade precision, high density, and calm. Surfaces are dark-first — the admin and user portals default to a near-black cockpit with a blue-violet tint — but the system ships three complete themes (light, dark, black-gold) and every feature is finished only when it reads right in all three, in both Chinese and English. Decoration is rationed: gradients, glare, and dimensional rendering belong to the instruments, the login button, and the public landing page; ordinary ops surfaces stay flat and quiet.

Confirmed visual rejections: no marketing fluff inside the product, no decorative use of status colors, no CDN-loaded assets of any kind.

**Key Characteristics:**
- Dark-first tri-theme system: light / dark / black-gold, all three mandatory
- Porsche-binnacle instrument language as the binding signature (always-dark dials, real redlines)
- Ops density: scan-and-act grids up to 8 metric columns on wide screens
- Restrained, precise components: ghost by default, solid only for primary actions
- Spring-physics motion with a binding `prefers-reduced-motion` path
- Bilingual by construction (zh primary, en parity), CJK-aware font stacks

## Colors

The palette is a dark cockpit of near-black neutrals, one cool action voice per portal (blue for admin, indigo-violet for user), a warm brass metal for the black-gold theme, and a strictly rationed set of signal colors that only ever mean state.

### Primary
- **Action Blue 行动蓝** (`#3b82f6`): the admin console's working accent — primary buttons, active nav edge, links, focus ring in light theme. Deepens to **Action Blue Deep** (`#2563eb`) on hover and in light-theme active tabs.
- **Aged Brass 陈年黄铜** (`#d4a853`): the black-gold theme's metal. Focus rings, active tabs, borders (`rgba(212,168,83,0.22–0.35)`), gold bezel rings and tick retints on the dials. Never a fill for large surfaces.
- **Signal Green 信号绿** (`#22c55e`): the public landing page accent and the green stroke in the logo. Hero highlights, primary landing buttons, mono section labels. Brightens to **Signal Green Bright** (`#4ade80`) on hover. It does not enter the ops consoles.

### Secondary
- **Indigo Focus 靛蓝聚焦** (`#818cf8`): the user portal's accent in dark mode — focus glows, checkbox accents, tint chips, the login gradient (`#6366f1 → #8b5cf6`).
- **Violet Active 紫罗兰选中** (`#a78bfa`): active tab text and underlines in the user portal's dark theme, where pure blue would fight the indigo glows.

### Tertiary
- **Redline 红线红** (`#ef4444`): errors, redline arc zones on dials, red tell-tale lamps, destructive actions. Structural, never decorative.
- **Telltale Amber 警示琥珀** (`#f59e0b`): degraded states, warning banners, amber lamps on the tach face.
- **Telltale Green 通行绿** (`#10b981`): healthy state, success rate segments, the "all normal" lamp. Distinct from Signal Green: this one reports status inside the consoles.

### Neutral
- **Cockpit Night 座舱夜黑** (`#050508`): dark-theme page base; a near-black with a blue-violet breath.
- **Night Panel 夜面板** (`#0a0a12`): dark-theme cards, nav, inputs.
- **Night Raised 夜抬升面** (`#14141f`): dark-theme raised chips, hover fills, secondary surfaces.
- **Night Text 夜文本** (`#ededf8`): dark-theme primary text, stepped down with alpha (`e6`/`b8`/`a3`/`7a`) for the muted hierarchy.
- **Zinc Abyss 深渊黑** (`#09090b`): landing page and black-gold page base (pure neutral, no violet).
- **Brass Panel 黄铜面板** (`#1a1814`): black-gold cards; secondary fills step to `#1c1917` and `#292524`; muted gold text is **Brass Muted 哑金文本** (`#c9b896`).
- **Paper 纸白** (`#ffffff`) and **Porcelain 瓷灰** (`#f3f4f6`): light-theme cards and page base, with Tailwind gray text (`#1f2937` primary, `#4b5563`–`#6b7280` muted).
- **Gauge Bezel 表圈钢** (`#9aa4b2`): the steel ring, tick, and hub metal of the instruments; gold themes retint it toward brass.

### Named Rules
**The Tri-Theme Parity Rule.** No screen ships until it renders correctly in light, dark, and black-gold. The shared focus ring is the audit probe: it must read `#3b82f6` in light, `#60a5fa` in dark, `#d4a853` in black-gold.

**The Dark Dial Rule.** Gauge faces stay dark (a `#12151c → #05070a` gradient) in every theme, including light. Themes change the bezel metal and tick color, never the dial face — the instrument is always a night instrument.

**The Signal Discipline Rule.** Red, amber, and telltale-green encode state only. A red that isn't an error, an amber that isn't a warning, or a green that isn't "healthy" is a bug.

## Typography

**Display Font:** Instrument Sans (with system-ui fallback) — public landing page only
**Body Font:** system sans stack (`ui-sans-serif, system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei'`) — all consoles; Microsoft YaHei carries Chinese text
**Label/Mono Font:** JetBrains Mono on the landing page; `ui-monospace, Menlo, Consolas` for logs, code, keys, and IPs. **Dial and gauge numerals are the exception:** they use `'Lucida Console', Menlo, Monaco, 'Courier New', monospace` because the default console monos (Cascadia/Consolas) render a slashed zero that corrupts numeric readouts — dial digits must be unambiguous at a glance

**Character:** A quiet, engineered sans for prose and a disciplined mono for anything measured. The pairing reads like the product: calm sentences, precise numbers. Chinese and English ship at equal weight; the CJK fallback is part of the stack, not an afterthought.

### Hierarchy
- **Display** (500, clamp(44px, 7vw, 84px), 1.05 line-height, -0.035em tracking): landing hero only. Never used inside the consoles.
- **Headline** (700, 1.25rem, 1.3): page and brand titles ("ModelGate" in the sidebar, page headers).
- **Title** (600, 1.125rem, 1.4): card and panel headings; scales down to 0.875–1rem on dense admin grids.
- **Body** (400, 0.875rem, 1.6): console default; the landing page relaxes to 16–17px with 1.6–1.75 line-height and a ~560px measure.
- **Label** (500, 0.75rem, 0.06em tracking, uppercase when mono): section eyebrows, stat-card captions, dial labels, timestamps.
- **Metric** (700, 1.875rem, tabular-nums): stat-card numerals with the flip-counter animation; always tabular lining figures.

### Named Rules
**The Tabular Numerals Rule.** Every live or comparable number is set with `font-variant-numeric: tabular-nums`. Digits may flip (the 0.6s digit-roll counter), but they may never jitter sideways.

**The Mono-for-Data Rule.** Anything measured, logged, keyed, or dialed is monospace; prose never is. Gauge numerals, odometer readouts, request IDs, API keys, and code blocks are mono — headlines and paragraphs are not.

## Layout

The admin console is a fixed **224px sidebar** (full viewport height, white/Night Panel, active item marked by a 3px right edge bar in Action Blue) plus a fluid `<main>` with 24px padding. Monitoring density is explicit: the top metric grid runs 2 columns below 768px, 4 at ≥768px, and 8 at ≥1680px — wide screens get more instruments, not more whitespace. The user portal is a centered container (max-width ~1200px) topped by a segmented pill tab bar; the landing page is a 1200px column with 24px gutters, a fixed 56px backdrop-blur nav, and generous vertical rhythm (160px hero top padding, 80px section spacing). Mobile gets dedicated templates (e.g. `mobile_home.html`) rather than squeezed desktop grids, and the instrument cluster stacks vertically below 640px. Spacing rides the Tailwind 4px scale; the observed rhythm is 8 / 12 / 16 / 20 / 24 / 32.

### Named Rules
**The Ops Density Rule.** On monitoring surfaces, add columns before you add air. A 1680px-wide screen shows eight metric cards; it does not show four cards with bigger margins.

## Elevation & Depth

Depth is doctrinally split: **instruments are dimensional, surfaces are quiet.** The binnacle panel and dial pods get the full physical treatment — bezel rings, inset dial wells, glass glare, a radial canopy shadow over the hood. Ordinary surfaces stay nearly flat: one soft shadow in light theme, and in dark themes a deep ambient shadow paired with a 1px inset top highlight (a machined edge catching light), never a glowing border or heavy blur.

### Shadow Vocabulary
- **Card rest (light)** (`0 1px 2px rgba(15,23,42,0.05)`): default admin/user cards.
- **Card shell (light)** (`0 1px 2px rgba(15,23,42,0.04), 0 12px 32px -16px rgba(15,23,42,0.14)`): the user portal's elevated containers.
- **Surface (dark / black-gold)** (`0 18px 36px rgba(0,0,0,0.55), inset 0 1px 0 rgba(235,234,250,0.06)`): dark cards and modals; black-gold swaps the inset highlight to `rgba(212,168,83,0.06)` and softens to 0.45 alpha.
- **Admin deep (dark)** (`0 12px 30px rgba(2,6,23,0.45)`): admin panels in dark mode.
- **Hover lift** (`translateY(-2px)` + `0 4px 12px rgba(0,0,0,0.12)`): stat cards respond to hover with a small physical lift.
- **Cluster panel** (`inset 0 1px 0 rgba(255,255,255,0.07), inset 0 18px 28px -14px rgba(0,0,0,0.75), 0 10px 30px rgba(0,0,0,0.35)`): the binnacle hood — a `#1c2027 → #12151a → #0c0e12` vertical gradient with a radial glare canopy.
- **Dial well** (`0 0 0 1px rgba(255,255,255,0.06), 0 8px 20px rgba(0,0,0,0.6), inset 0 2px 12px rgba(0,0,0,0.7)`): the recessed instrument face.
- **Focus glow** (`0 0 0 3px rgba(129,140,248,0.18)`): input focus in the user portal; elsewhere focus is a 2px themed outline with 2px offset.

### Named Rules
**The Quiet-Surface Rule.** Dimensional rendering — bezels, insets, glare, deep wells — is reserved for gauges and their pods. A plain card with an instrument shadow is overdressed.

**The Inset-Highlight Rule.** In dark themes, elevation reads as `deep soft shadow + 1px inset top highlight`. Do not substitute brighter borders or blur-heavy glows.

## Shapes

The form language is machined and rounded at small radii. Controls and admin buttons curve gently (4px), standard buttons and cards sit at 8px, segmented tab pills pair a 14px track with 10px buttons, modals and the login card round to 16px, and the binnacle panel tops the scale at 18px. Pills (9999px) belong to health badges, concurrency bars, and filter chips. The instrument cluster introduces the system's only circles: dial faces, tell-tale lamps, status dots — always perfect circles, always with a bezel or ring. The sidebar's active state is a 3px straight edge bar, the one deliberately sharp note, like a needle index mark.

### Named Rules
**The Sacred Circle Rule.** Perfect circles belong to dials, lamps, and status dots. Avatars, buttons, and cards are never circular — a circle promises an instrument.

## Components

### Buttons
Restrained by default, solid only when the action is primary.
- **Shape:** gently curved (4px in the admin console, 8px in the user portal and landing).
- **Primary:** Action Blue fill, white text, compact padding (8px 24px); hover deepens to Action Blue Deep. On the landing page, primary is Signal Green with Zinc Abyss text (11px 22px), hover brightens and lifts a soft shadow.
- **Hover / Focus:** 0.15s background transitions; focus is always the themed 2px outline (never removed), with the indigo 3px glow reserved for text inputs in the user portal.
- **Ghost:** Paper background, `#e5e7eb` stroke, `#4b5563` text (6px 12px); hover fills Porcelain. Dark themes redraw it as Night Panel fill with a 10–14% white border.
- **Gradient (one exception):** the login button runs `#6366f1 → #8b5cf6` with an inset top highlight and a violet drop shadow; hover brightens both stops. It is the only gradient button in the product.

### Tabs & Segmented Controls
- **Style:** a pillbox track (14px radius, `#f1f5f9` / dark `rgba(235,234,250,0.03)` / brass `#141210`) holding 10px-radius buttons; the active button is a raised Paper chip with a hairline ring shadow.
- **State:** dark theme recolors the active chip to a translucent indigo fill with Violet Active text; black-gold uses a 14% brass fill with Aged Brass text. Client sub-tabs use a simpler 2px bottom underline in the theme accent.

### Cards / Containers
- **Corner Style:** 8px for grid cards, 16px for modals and glass cards, 18px for the instrument cluster.
- **Background:** Paper in light; a 3% white glass fill or Night Panel in dark; Brass Panel in black-gold.
- **Shadow Strategy:** see Elevation — Quiet-Surface Rule for cards, full physical treatment only for instrument pods.
- **Border:** hairline only — `rgba(15,23,42,0.06)` light, 8% white dark, 22–25% brass in black-gold.
- **Internal Padding:** 16px in dense admin grids, 20px in stat cards, 24–32px in modals.

### Inputs / Fields
- **Style:** Paper background, `#e5e7eb` stroke, 8px radius, 13–14px text; dark themes invert to Night Panel with a 10–14% white border.
- **Focus:** 2px themed outline globally; user-portal text inputs additionally bloom a 3px indigo glow at 18% alpha with the border shifting to Indigo Focus.
- **Error / Disabled:** errors speak Redline red as text below the field; disabled controls drop to ~70% opacity and `not-allowed`.

### Badges & Status
- **Health pills:** fully rounded (9999px), 12px 700-weight numerals, five statuses — excellent (green), good (blue), warning (amber), critical (red), unavailable (slate) — each a soft tinted fill with a deep text color in light, a 16% alpha fill with a brightened text color in dark.
- **Tell-tale lamps:** 10px circles with a 1.5px steel ring; unlit they are empty bezels, lit they fill with signal color and a pulsing glow (red/amber) or a steady halo (green). Pulsing stops under reduced motion.

### Navigation
- **Admin sidebar:** fixed 224px column; links are 14px with a 20px stroke icon, 12px 16px padding; hover washes 10% blue, the active link takes a 10% blue fill plus the 3px right edge bar. Dark theme keeps the same geometry with Night Panel fill and `#60a5fa` accents.
- **Landing nav:** fixed 56px bar, 85% Zinc Abyss with 16px backdrop blur and a 6% white bottom border; 14px quiet links that brighten on hover; language select in 12px mono.
- **User portal:** top-aligned segmented pill tabs (see Tabs), horizontally scrollable with hidden scrollbars.

### The Instrument Cluster (signature)
The five-dial binnacle is the system's signature component and its craft benchmark. An 18px-radius panel with a machined vertical gradient and glare canopy holds dark dial pods: a leaderboard info dial, a speedometer, the central tachometer (240px, 270° sweep, redline arc, four corner tell-tale lamps), a segmented health dial, and a fuel-style capacity dial. Needles are driven by a spring integrator (stiffness 280, damping 50, mass 1) — never CSS transitions — with tabular mono readouts in an inset odometer window. Gauge ranges encode real capacity and redlines mark real thresholds; decorative sweeps are forbidden. The same miniaturized tach pod appears on the user dashboard for per-model concurrency.

### Motion
- **Easings:** `cubic-bezier(0.25, 1, 0.5, 1)` for counters and reveals; `cubic-bezier(0.22, 1, 0.36, 1)` for pops and settles; 0.15s for control feedback, 0.2s for hovers, 0.6s for digit rolls and section reveals.
- **Signature motion:** the digit-roll flip counter on live metrics, spring-physics needles, and the landing page's spring counters and ambient particles (particles run only on dark surfaces).
- **The Reduced-Motion Rule (binding).** Every animation ships a `prefers-reduced-motion: reduce` path that removes non-essential motion — lamp pulses stop, digit rolls snap, needle springs settle instantly. This is a product requirement, not a nicety.

## Do's and Don'ts

### Do:
- **Do** ship every screen in all three themes; verify the focus ring reads `#3b82f6` / `#60a5fa` / `#d4a853` in light / dark / black-gold.
- **Do** keep dial faces dark (`#12151c → #05070a`) in all themes; retint only the bezel metal, ticks, and text toward brass in black-gold.
- **Do** set every live number in tabular-nums and drive numeric changes through the flip counter or the spring integrator (stiffness 280, damping 50).
- **Do** keep Chinese and English at parity; the body stack must include Microsoft YaHei, and CJK line-length comfort takes precedence on zh screens.
- **Do** reserve Signal Green for the landing page and logo; the consoles speak Action Blue (admin) and Indigo/Violet (user).
- **Do** give every animation a `prefers-reduced-motion` path before calling the feature done.
- **Do** make gauge ranges truthful: sweep equals effective capacity, redline equals the real threshold.

### Don't:
- **Don't** load fonts, icons, scripts, or CSS from a CDN — every asset is self-hosted under `web/static`.
- **Don't** use gradient fills decoratively; gradients belong to the binnacle panel, the login button, and the landing hero glow only.
- **Don't** use Redline red, Telltale Amber, or Telltale Green as branding or decoration — they encode state (Signal Discipline Rule).
- **Don't** introduce border radii outside the established scale (4 / 6 / 8 / 10 / 12 / 14 / 16 / 18px, pill).
- **Don't** approximate elevation in dark themes with bright borders or heavy blur — use the deep-shadow-plus-inset-highlight formula.
- **Don't** animate gauge needles with CSS transitions or keyframes; physical needle motion comes from the spring integrator.
- **Don't** write marketing copy inside the product; console voice is concise and operational.
