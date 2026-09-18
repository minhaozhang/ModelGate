import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
TEMPLATES = WEB / "templates"


class LoginPagesUseParticleBgTests(unittest.TestCase):
    def test_no_template_references_three_min_js(self):
        offenders = []
        for path in TEMPLATES.rglob("*.html"):
            if "three.min.js" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(TEMPLATES)))
        self.assertEqual(offenders, [], "templates must not load three.min.js")

    def test_three_min_js_file_removed_from_static(self):
        self.assertFalse((WEB / "static" / "js" / "three.min.js").exists())

    def test_login_pages_load_particle_bg_and_dark_theme(self):
        for rel in ("admin/login.html", "user/login.html"):
            html = (TEMPLATES / rel).read_text(encoding="utf-8")
            with self.subTest(page=rel):
                self.assertIn("particle-bg.js", html)
                self.assertIn("particle-bg.css", html)
                self.assertIn("ParticleBG.setTheme('dark')", html)
                self.assertNotIn("THREE.", html)
                self.assertNotIn("particles-container", html)
                self.assertIn("background: #050508", html)


if __name__ == "__main__":
    unittest.main()
