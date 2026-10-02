import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class ModelConcurrencyGauge3DTests(unittest.TestCase):
    """Porsche-cluster gauge: black face, tick ring with scale numbers,
    white blade needle with colored tip, glowing value arc, spring motion."""

    FILES = ("web/templates/user/dashboard.html", "web/templates/user/tab_stats_v2.html")

    def test_gauge_markers_present(self):
        for rel in self.FILES:
            html = _read(rel)
            for marker in (
                "mc-face-a", "mc-face-b",       # radial black dial face
                "mc-ring", "mc-groove",         # bezel ring + arc groove
                "mc-tick-major", "_mcTicks()",  # full graduation ring
                "mc-num-mid", "mc-num-max",     # dynamic scale numbers
                "mc-needle-body", "mc-needle-tip",
                "mc-hub-cap", "mc-glass",
                "feGaussianBlur",               # value-arc glow
                "_mcSetNeedleColor", "_mcShade",
                "card.numMax.textContent = eff;",
                "card.numMid.textContent = Math.round(eff / 2);",
            ):
                self.assertIn(marker, html, f"{rel} missing {marker}")

    def test_zero_arc_dot_guard(self):
        # A zero-length dash with round linecap paints a stray dot at the
        # scale start; the arc pair must hide until there is arc to show.
        for rel in self.FILES:
            html = _read(rel)
            self.assertIn("pct > 0.005 ? 'visible' : 'hidden'", html, rel)

    def test_gold_ring_gradient_defs(self):
        # Both gauge lists render on the same page, so their shared-document
        # gold ring gradients need distinct ids, defined outside the lists
        # (list containers get their innerHTML rewritten).
        d_css, d_tab = _read("web/templates/user/dashboard.html"), _read("web/templates/user/tab_stats.html")
        v_css, v_tab = _read("web/templates/user/tab_stats_v2.html"), _read("web/templates/user/tab_stats_v2.html")
        self.assertIn("url(#mc-ring-gold-d)", d_css)
        self.assertIn('id="mc-ring-gold-d"', d_tab)
        self.assertIn("url(#mc-ring-gold-v)", v_css)
        self.assertIn('id="mc-ring-gold-v"', v_tab)

    def test_superseded_skeuomorphic_markers_gone(self):
        for rel in self.FILES:
            html = _read(rel)
            for stale in (
                "mc-needle-tail", "mc-bezel", "mc-dial-wrap", "rotateX",
                "feDropShadow", "mc-needle-hl", "mc-hub-mid", "mc-hub-dot",
                "mc-track", "mc-plate", "needleStops",
            ):
                self.assertNotIn(stale, html, f"{rel} still has {stale}")

    def test_needle_uses_spring_integrator(self):
        for rel in self.FILES:
            html = _read(rel)
            self.assertIn("velPct", html)
            self.assertIn("card.velPct = (v + d * 0.02) * 0.8;", html)
            self.assertNotIn("d * 0.14", html, "old lerp easing must be gone")


class ClipboardCopyFallbackTests(unittest.TestCase):
    """navigator.clipboard is undefined on plain-HTTP deployments (secure
    context required); bare calls throw and kill the copy buttons."""

    def test_dashboard_copy_calls_are_guarded(self):
        html = _read("web/templates/user/dashboard.html")
        self.assertIn("function copyTextToClipboard(", html)
        self.assertIn("function legacyCopy(", html)
        self.assertIn("navigator.clipboard && window.isSecureContext", html)
        self.assertIn("document.execCommand('copy')", html)
        # The ONLY writeText call sits inside the guarded helper.
        self.assertEqual(html.count("navigator.clipboard.writeText"), 1)

    def test_opencode_copy_is_guarded(self):
        html = _read("web/templates/public/opencode.html")
        self.assertIn("navigator.clipboard && window.isSecureContext", html)
        self.assertIn("legacyCopy(", html)

    def test_copy_failed_copy_is_translated(self):
        po = _read("web/locales/zh/LC_MESSAGES/messages.po")
        self.assertIn('msgid "Copy failed, please copy manually"', po)
        self.assertIn("复制失败，请手动复制", po)


class UserDarkThemePaletteTests(unittest.TestCase):
    """theme-dark must follow the index-c deep-space violet palette."""

    def test_dashboard_uses_deep_space_palette(self):
        css = _read("web/templates/user/dashboard.html")

        self.assertIn("background: #050508", css)
        self.assertIn("rgba(235, 234, 250, 0.03)", css)
        self.assertIn("rgba(235, 234, 250, 0.08)", css)
        self.assertIn("color: #ededf8", css)
        self.assertIn("color: #a78bfa", css)
        self.assertIn("rgba(129, 140, 248, 0.14)", css)

    def test_dashboard_drops_old_slate_dark_tokens(self):
        css = _read("web/templates/user/dashboard.html")
        dark_block = css[css.index("body.theme-dark"):css.index("body.theme-blackgold")]

        self.assertNotIn("#020617", dark_block)
        self.assertNotIn("#0f172a", dark_block)
        self.assertNotIn("#93c5fd", dark_block)
        self.assertNotIn("#0b1120", dark_block)

    def test_documents_pages_use_deep_space_palette(self):
        for rel in (
            "web/templates/user/documents.html",
            "web/templates/user/document_detail.html",
        ):
            css = _read(rel)
            dark_block = css[
                css.index("body.theme-dark"):css.index("body.theme-blackgold")
            ]
            self.assertIn("#050508", dark_block, rel)
            self.assertIn("rgba(235, 234, 250, 0.03)", dark_block, rel)
            self.assertIn("#ededf8", dark_block, rel)

    def test_dashboard_chart_theme_dark_branch_follows_palette(self):
        html = _read("web/templates/user/dashboard.html")
        theme_fn = html[html.index("function getChartTheme"):html.index("function applyTheme")]

        self.assertIn("#0a0a12", theme_fn)
        self.assertIn("rgba(235, 234, 250, 0.14)", theme_fn)


class ParticleBackgroundTests(unittest.TestCase):
    def test_shared_particle_assets_exist(self):
        js = _read("web/static/js/particle-bg.js")
        css = _read("web/static/css/particle-bg.css")

        self.assertIn("ParticleBG", js)
        self.assertIn("setEnabled", js)
        self.assertIn("requestAnimationFrame", js)

        self.assertIn("particle-bg-canvas", css)
        self.assertIn("body.has-particle-bg", css)

    def test_particle_brightness_is_edge_weighted(self):
        js = _read("web/static/js/particle-bg.js")

        self.assertIn("edgeBoost", js)
        self.assertIn("alphaMin: 0.35", js)
        self.assertIn("alphaMax: 0.85", js)
        self.assertIn("linkAlpha: 0.22", js)
        self.assertIn("centerFloor: 0.55", js)

    def test_particles_drift_forever(self):
        js = _read("web/static/js/particle-bg.js")

        # uniform horizontal spread (no edge bias)
        self.assertIn("x: Math.random() * width", js)
        self.assertNotIn("seedX", js)
        # damping alone freezes particles; a minimum speed re-energizes them
        self.assertIn("sp2 < 0.01", js)

    def test_link_pulses_replace_scanline(self):
        js = _read("web/static/js/particle-bg.js")
        css = _read("web/static/css/particle-bg.css")

        # scanline machinery is fully gone (js + css)
        for gone in ("SCAN_PERIOD_MS", "scanStart", "scanGlow", "particle-scan-line"):
            self.assertNotIn(gone, js)
        self.assertNotIn("particle-scan-line", css)
        self.assertNotIn("particleScanDown", css)

        # link pulses: hop along links, glow visited particles, fade out
        self.assertIn("PULSE_SPEED = 0.35", js)
        self.assertIn("hopsLeft", js)
        self.assertIn("neighborsOf", js)
        self.assertIn("pl.to.glow = 1", js)
        self.assertIn("p.glow *= 0.94", js)
        # long chains: 8-16 hops per pulse
        self.assertIn("hopsLeft: 8 + Math.floor(Math.random() * 9)", js)
        # no retracing ever + progressive far-arc ladder keeps paths moving
        self.assertIn("pl.seen.indexOf(q) < 0", js)
        self.assertIn("arcs = [2, 3.5, 5]", js)
        self.assertIn("conf.linkDist * arcs[ai]", js)
        self.assertIn("seen: pl.seen.slice()", js)
        # lightning forks: 35% chance a pulse splits into a second branch
        self.assertIn("Math.random() < 0.35", js)
        self.assertIn("hopsLeft: 3 + Math.floor(Math.random() * 4)", js)
        self.assertIn("width < 768 ? 2 : 3", js)
        # spawn cadence and concurrency cap
        self.assertIn("2500 + Math.random() * 3000", js)
        self.assertIn("pulses.length < pulseMax()", js)
        # light theme stays pure particles
        self.assertIn("theme !== 'light'", js)

    def test_particle_theme_palettes_exist(self):
        js = _read("web/static/js/particle-bg.js")

        self.assertIn("setTheme", js)
        for theme in ("dark", "blackgold", "light"):
            self.assertIn(f"{theme}: {{", js)
        self.assertIn("particle-bg-blackgold", js)
        self.assertIn("particle-bg-light", js)

    def test_dark_pages_wire_particle_background(self):
        for rel in (
            "web/templates/user/dashboard.html",
            "web/templates/user/documents.html",
            "web/templates/user/document_detail.html",
        ):
            html = _read(rel)
            self.assertIn("particle-bg.js", html, rel)
            self.assertIn("particle-burst.js", html, rel)
            self.assertIn("ParticleBG.setTheme", html, rel)

    def test_theme_switch_toggles_particles(self):
        html = _read("web/templates/user/dashboard.html")
        apply_fn = html[html.index("function applyTheme"):html.index("function applyTheme") + 700]

        self.assertIn("ParticleBG.setTheme(mode)", apply_fn)

    def test_dark_modals_are_opaque(self):
        html = _read("web/templates/user/dashboard.html")

        # the glassy 3%-alpha dark card treatment must not apply to modal
        # panels: they float over a dimmed overlay and need a solid backdrop
        self.assertIn("body.theme-dark #my-requests-modal > div", html)
        self.assertIn("body.theme-dark #price-detail-modal > div", html)
        self.assertIn("background: #0a0a12 !important", html)


class GlobalStatusStripTests(unittest.TestCase):
    def test_dashboard_has_global_status_strip(self):
        html = _read("web/templates/user/dashboard.html")

        self.assertIn('id="global-status-strip"', html)
        self.assertIn("function renderGlobalStrip", html)
        self.assertIn("lastLiveCounts = { users: count, requests: data.request_count || 0 }", html)
        self.assertIn("高峰中 · 错峰使用更快", html)
        self.assertIn("低谷时段 · 现在用更流畅", html)
        self.assertIn("ratio429 > 0.05", html)

    def test_dashboard_theme_overrides_for_strip(self):
        html = _read("web/templates/user/dashboard.html")

        self.assertIn("body.theme-dark #global-status-strip", html)
        self.assertIn("body.theme-blackgold #global-status-strip", html)

    def test_stats_tab_old_busyness_banner_removed(self):
        html = _read("web/templates/user/tab_stats.html")

        self.assertNotIn("busyness-banner", html)
        self.assertNotIn("busyness-dot", html)
        self.assertNotIn("busyness-label", html)

    def test_system_active_api_returns_busyness(self):
        src = _read("app/routes/user.py")
        endpoint = src[
            src.index('"/user/api/system-active"'):src.index("user_live_stats_websocket")
        ]

        self.assertIn('"sessions": sessions', endpoint)
        self.assertIn('"busyness": dict(busyness_state)', endpoint)


class LoginDeepSpaceThemeTests(unittest.TestCase):
    def test_login_uses_deep_space_palette(self):
        html = _read("web/templates/user/login.html")

        self.assertIn("background: #050508", html)
        self.assertIn("rgba(235, 234, 250, 0.03)", html)
        self.assertIn("rgba(235, 234, 250, 0.08)", html)
        self.assertIn("linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)", html)
        self.assertNotIn("from-blue-500 to-purple-500", html)

    def test_login_particle_palette_is_indigo_family(self):
        bg = _read("web/static/js/particle-bg.js")

        self.assertIn("[129, 140, 248]", bg)
        self.assertIn("[167, 139, 250]", bg)
        self.assertNotIn("[220, 68, 55]", bg)
        self.assertIn("ParticleBG.setTheme('dark')", _read("web/templates/user/login.html"))

    def test_login_respects_reduced_motion(self):
        bg = _read("web/static/js/particle-bg.js")

        self.assertIn("prefers-reduced-motion", bg)
        self.assertIn("REDUCE_MOTION", bg)


if __name__ == "__main__":
    unittest.main()
