import unittest
from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "particle-burst.js").read_text(encoding="utf-8")


class ParticleBurstAnywhereTests(unittest.TestCase):
    def test_click_bursts_anywhere_except_text_inputs(self):
        self.assertNotIn("CLICK_TARGETS", JS)
        self.assertIn('input, textarea, [contenteditable="true"]', JS)

    def test_burst_particles_can_survive_as_floaters(self):
        self.assertIn("PERSIST_CHANCE", JS)
        self.assertIn("convertToFloat", JS)

    def test_floaters_capped_with_graceful_fade(self):
        self.assertIn("MAX_FLOATERS = 60", JS)
        self.assertIn("evictOldestFloater", JS)
        self.assertIn("'dying'", JS)

    def test_shockwave_pushes_existing_floaters(self):
        self.assertIn("function shockwave(", JS)
        self.assertIn("SHOCK_RADIUS", JS)

    def test_floaters_breathe_and_wrap_edges(self):
        self.assertIn("FLOAT_BREATH_MS", JS)
        self.assertIn("breath", JS)
        self.assertIn("canvas.width + 8", JS)


if __name__ == "__main__":
    unittest.main()
