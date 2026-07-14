"""Unit tests for subtitle wrapping, safe zones, and placement (pure)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subtitles.layout import (CANVAS_H, CANVAS_W, SAFE_ZONE, Rect, block_size,
                              place_block, wrap_text)


def char_measure(text):
    """Fake font: every character is 20px wide."""
    return len(text) * 20


class TestWrapText(unittest.TestCase):
    def test_no_wrap_when_it_fits(self):
        self.assertEqual(wrap_text("hold me close", 400, char_measure),
                         ["hold me close"])

    def test_wraps_at_word_boundaries(self):
        lines = wrap_text("hold me close under the light", 300, char_measure)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(char_measure(line), 300)
        self.assertEqual(" ".join(lines), "hold me close under the light")

    def test_overlong_word_is_force_broken(self):
        lines = wrap_text("a Supercalifragilistic b", 200, char_measure)
        for line in lines:
            self.assertLessEqual(char_measure(line), 200)
        self.assertTrue(any(line.endswith("-") for line in lines))

    def test_empty(self):
        self.assertEqual(wrap_text("", 200, char_measure), [])

    def test_block_size(self):
        w, h = block_size(["abc", "a"], char_measure, line_height=50, line_gap=8)
        self.assertEqual(w, 60)
        self.assertEqual(h, 108)


class TestSafeZone(unittest.TestCase):
    def test_zone_avoids_phone_ui_areas(self):
        self.assertGreaterEqual(SAFE_ZONE.y, 200)                    # top overlays
        self.assertLessEqual(SAFE_ZONE.bottom, CANVAS_H - 300)       # bottom UI
        self.assertLessEqual(SAFE_ZONE.right, CANVAS_W - 150)        # right rail

    def test_rect_helpers(self):
        a, b = Rect(0, 0, 10, 10), Rect(5, 5, 10, 10)
        self.assertTrue(a.intersects(b))
        self.assertEqual(a.overlap_area(b), 25.0)
        self.assertFalse(a.intersects(Rect(10, 0, 5, 5)))  # touching edges


class TestPlaceBlock(unittest.TestCase):
    def test_always_inside_safe_zone(self):
        for seed in range(24):
            for preferred in ("lower", "center", "upper"):
                rect = place_block((700, 260), preferred=preferred, seed=seed)
                self.assertTrue(SAFE_ZONE.contains_rect(rect),
                                f"escaped safe zone: {rect}")

    def test_deterministic_but_varies_by_seed(self):
        a1 = place_block((500, 200), seed=3)
        a2 = place_block((500, 200), seed=3)
        b = place_block((500, 200), seed=4)
        self.assertEqual((a1.x, a1.y), (a2.x, a2.y))
        self.assertNotEqual((a1.x, a1.y), (b.x, b.y))

    def test_avoids_focal_rect(self):
        face = Rect(SAFE_ZONE.x, SAFE_ZONE.y + SAFE_ZONE.h * 0.6,
                    SAFE_ZONE.w, SAFE_ZONE.h * 0.4)  # whole lower band busy
        rect = place_block((500, 200), avoid=[face], preferred="lower", seed=1)
        self.assertFalse(rect.intersects(face))
        self.assertTrue(SAFE_ZONE.contains_rect(rect))

    def test_least_overlap_fallback_when_everything_busy(self):
        everything = Rect(0, 0, CANVAS_W, CANVAS_H)
        rect = place_block((500, 200), avoid=[everything], seed=2)
        self.assertTrue(SAFE_ZONE.contains_rect(rect))

    def test_oversized_block_clamped_to_zone(self):
        rect = place_block((5000, 5000), seed=0)
        self.assertTrue(SAFE_ZONE.contains_rect(rect))


class TestFontShaping(unittest.TestCase):
    """Arabic/Hebrew must get a glyph-capable font and be shaped."""

    def test_script_detection(self):
        from subtitles import fonts
        self.assertTrue(fonts.has_arabic("مش هسمحلك"))
        self.assertTrue(fonts.is_rtl("مش هسمحلك"))
        self.assertFalse(fonts.has_arabic("hold on tight"))
        self.assertFalse(fonts.is_rtl("bülbül bülbül"))

    def test_arabic_font_path_exists(self):
        """The chosen Arabic font must be a real file (else glyphs tofu)."""
        from pathlib import Path
        from subtitles import fonts
        latin = "/System/Library/Fonts/Supplemental/AmericanTypewriter.ttc"
        resolved = fonts.font_for("قلبي", latin)
        self.assertNotEqual(resolved, latin, "no Arabic font resolved")
        self.assertTrue(Path(resolved).exists(), resolved)

    def test_arabic_gets_non_latin_font(self):
        from subtitles import fonts
        latin = "/System/Library/Fonts/Supplemental/AmericanTypewriter.ttc"
        self.assertNotEqual(fonts.font_for("مش هسمحلك", latin), latin)
        self.assertEqual(fonts.font_for("hold on", latin), latin)

    def test_shape_reorders_arabic_and_passes_latin(self):
        from subtitles import fonts
        self.assertEqual(fonts.shape("hold on tight"), "hold on tight")
        shaped = fonts.shape("مش هسمحلك")
        self.assertTrue(shaped)                    # non-empty
        # bidi puts it in visual order; reshaping changes the codepoints
        self.assertNotEqual(shaped, "مش هسمحلك")


if __name__ == "__main__":
    unittest.main()
