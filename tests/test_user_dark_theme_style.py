import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


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


class LoginDeepSpaceThemeTests(unittest.TestCase):
    def test_login_uses_deep_space_palette(self):
        html = _read("web/templates/user/login.html")

        self.assertIn("0x050508", html)
        self.assertIn("rgba(235, 234, 250, 0.03)", html)
        self.assertIn("rgba(235, 234, 250, 0.08)", html)
        self.assertIn("linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)", html)
        self.assertNotIn("from-blue-500 to-purple-500", html)

    def test_login_particle_palette_is_indigo_family(self):
        html = _read("web/templates/user/login.html")
        palette = html[html.index("colorPalette") : html.index("rings =")]

        self.assertIn("0.51, 0.55, 0.97", palette)
        self.assertIn("0.39, 0.43, 0.95", palette)
        self.assertNotIn("0.96, 0.26, 0.21", palette)

    def test_login_respects_reduced_motion(self):
        html = _read("web/templates/user/login.html")

        self.assertIn("prefers-reduced-motion", html)


if __name__ == "__main__":
    unittest.main()
