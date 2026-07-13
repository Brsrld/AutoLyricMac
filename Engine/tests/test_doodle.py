"""Unit tests for the doodle library, selection, and placement (Phase 6)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "render"))

import numpy as np

from doodle_library import (LIBRARY, build_doodle, is_ground_anchored,
                            pick_doodle)
from doodle_renderer import doodle_layout, doodle_screen_rect

REQUIRED_CATEGORIES = {
    # spec: people states, parent-child, play, window/sky, cooking, water,
    # fire, sun, stone, loneliness, distance, reunion, memory, home
    "person": "standing_figure", "walking": "walking_figure",
    "talking": "talking_pair", "child": "sitting_child",
    "embrace": "hugging_pair", "play": "playing_child",
    "window": "window_frame", "sky": "flying_birds",
    "cooking": "steam_squiggle", "water": "raindrops",
    "fire": "candle_flame", "sun": "sun", "stone": "stone_pile",
    "solitude": "lonely_bench", "distance": "open_road",
    "reunion": "reunion_pair", "memory": "photo_frame", "home": "little_house",
}


class TestLibrary(unittest.TestCase):
    def test_all_required_categories_covered(self):
        all_tags = {t for _, tags, _ in LIBRARY.values() for t in tags}
        for tag in REQUIRED_CATEGORIES:
            self.assertIn(tag, all_tags, f"no doodle covers {tag!r}")

    def test_assets_are_transparent_rgba_with_navy_and_cream(self):
        for name in ("walking_figure", "little_house", "lonely_bench",
                     "moon_stars", "reunion_pair"):
            img = build_doodle(name, height=220)
            self.assertEqual(img.mode, "RGBA")
            arr = np.asarray(img)
            alpha = arr[..., 3]
            self.assertLess(alpha[alpha > 0].size / alpha.size, 0.95,
                            f"{name} background must stay transparent")
            opaque = arr[alpha > 200][..., :3]
            self.assertTrue(opaque.size, name)
            # navy outline present: dark pixels with blue dominance
            dark = opaque[opaque.sum(axis=1) < 300]
            self.assertTrue(len(dark) > 0, f"{name} has no dark outline")
            self.assertGreater(int(dark[:, 2].mean()), int(dark[:, 0].mean()),
                               f"{name} outline should lean navy-blue")

    def test_build_is_deterministic(self):
        a = np.asarray(build_doodle("hugging_pair", height=180))
        b = np.asarray(build_doodle("hugging_pair", height=180))
        self.assertTrue((a == b).all())


class TestPickDoodle(unittest.TestCase):
    def test_subject_match(self):
        self.assertEqual(pick_doodle(["embrace", "light"], 0), "hugging_pair")
        self.assertEqual(pick_doodle(["window"], 0), "window_frame")
        self.assertEqual(pick_doodle(["stone"], 0), "stone_pile")

    def test_no_match_means_no_doodle(self):
        for i in range(4):
            self.assertIsNone(pick_doodle(["zzz"], i))
        self.assertIsNone(pick_doodle([], 0))

    def test_synonyms_map_to_library(self):
        self.assertEqual(pick_doodle(["nightingale"], 0), "flying_birds")
        self.assertEqual(pick_doodle(["bülbül"], 0), "flying_birds")

    def test_ties_vary_by_index_deterministically(self):
        a = pick_doodle(["love"], 0)
        b = pick_doodle(["love"], 1)
        self.assertEqual(a, pick_doodle(["love"], 0))
        self.assertIn(a, LIBRARY)
        self.assertIn(b, LIBRARY)


class TestDoodleLayout(unittest.TestCase):
    def test_ground_anchored_stand_on_lower_third(self):
        for i in range(10):
            lay = doodle_layout(i, "standing_figure", True)
            self.assertGreaterEqual(lay["bottom_frac"], 0.80)
            self.assertLessEqual(lay["bottom_frac"], 0.92)
            self.assertTrue(0.2 <= lay["x_center"] <= 0.8)

    def test_sky_doodles_float_up_top(self):
        for i in range(10):
            lay = doodle_layout(i, "sun", False)
            self.assertLessEqual(lay["bottom_frac"], 0.45)

    def test_sides_alternate(self):
        a = doodle_layout(0, "standing_figure", True)
        b = doodle_layout(1, "standing_figure", True)
        self.assertNotEqual(a["side"], b["side"])

    def test_screen_rect_sane(self):
        lay = doodle_layout(2, "standing_figure", True)
        rect = doodle_screen_rect(lay, aspect=0.6)
        self.assertGreater(rect.w, 0)
        self.assertGreaterEqual(rect.y, 0)
        self.assertLessEqual(rect.bottom, 1920)


if __name__ == "__main__":
    unittest.main()
