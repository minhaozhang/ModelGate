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
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn("requestAnimationFrame", js)

        self.assertIn("particle-bg-canvas", css)
        self.assertIn("particle-scan-line", css)
        self.assertIn("body.has-particle-bg", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_dark_pages_wire_particle_background(self):
        for rel in (
            "web/templates/user/dashboard.html",
            "web/templates/user/documents.html",
            "web/templates/user/document_detail.html",
        ):
            html = _read(rel)
            self.assertIn("particle-bg.js", html, rel)
            self.assertIn("ParticleBG.setEnabled", html, rel)

    def test_theme_switch_toggles_particles(self):
        html = _read("web/templates/user/dashboard.html")
        apply_fn = html[html.index("function applyTheme"):html.index("function applyTheme") + 700]

        self.assertIn("ParticleBG.setEnabled(mode === 'dark')", apply_fn)


if __name__ == "__main__":
    unittest.main()
