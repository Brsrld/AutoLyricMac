"""Unit tests for the Archive Collage pure layout rules (Phase 5)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "render"))

from archive_renderer import photo_screen_rect, scene_layout
from subtitles.layout import SAFE_ZONE


def scene(motion_type="slow_push", amount=0.06):
    return {"motion": {"type": motion_type, "amount": amount,
                       "pulse_beats": []}}


class TestSceneLayout(unittest.TestCase):
    def test_photo_width_within_style_guide(self):
        for i in range(24):
            layout = scene_layout(scene(), i)
            self.assertGreaterEqual(layout["photo_w"], 0.55)
            self.assertLessEqual(layout["photo_w"], 0.90)

    def test_rotation_below_one_point_five_degrees_but_never_flat(self):
        for i in range(24):
            rot = scene_layout(scene(), i)["rotation"]
            self.assertLessEqual(abs(rot), 1.5)
            self.assertGreaterEqual(abs(rot), 0.3)

    def test_blocks_use_grey_black_white_palette_and_sane_sizes(self):
        for i in range(12):
            for blk in scene_layout(scene(), i)["blocks"]:
                r, g, b = blk["color"]
                self.assertLess(max(r, g, b) - min(r, g, b), 12,
                                "blocks must stay neutral grey/black/white")
                self.assertTrue(0.1 <= blk["size"][0] <= 0.35)
                self.assertTrue(120 <= blk["alpha"] <= 250,
                                "blocks must stay translucent-ish")

    def test_consecutive_scenes_differ_in_position(self):
        positions = [scene_layout(scene(), i)["photo_pos"] for i in range(6)]
        for a, b in zip(positions, positions[1:]):
            self.assertNotAlmostEqual(a[0], b[0], places=2)

    def test_motion_types_map_to_zoom_direction(self):
        push = scene_layout(scene("slow_push"), 0)
        pull = scene_layout(scene("slow_pull"), 0)
        self.assertGreater(push["zoom"][1], push["zoom"][0])
        self.assertGreater(pull["zoom"][0], pull["zoom"][1])
        # zoom never exceeds a slow editorial range
        for i in range(12):
            z = scene_layout(scene(amount=0.08), i)["zoom"]
            self.assertLess(max(z), 1.10)

    def test_deterministic(self):
        self.assertEqual(scene_layout(scene(), 3), scene_layout(scene(), 3))

    def test_photo_rect_overlaps_canvas_for_subtitle_avoidance(self):
        for i in range(8):
            rect = photo_screen_rect(scene_layout(scene(), i))
            self.assertGreater(rect.w, 0)
            self.assertGreater(rect.h, 0)
            # the photo must sit somewhere the subtitle zone cares about
            self.assertLess(rect.x, SAFE_ZONE.right)


if __name__ == "__main__":
    unittest.main()
