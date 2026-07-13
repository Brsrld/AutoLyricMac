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
    def test_photo_width_alternates_full_and_panel(self):
        # reference videos: centered artwork, full-bleed-ish and small-panel
        for i in range(0, 24, 2):
            self.assertGreaterEqual(scene_layout(scene(), i)["photo_w"], 0.84)
        for i in range(1, 24, 2):
            layout = scene_layout(scene(), i)
            self.assertTrue(0.46 <= layout["photo_w"] <= 0.60)

    def test_rotation_nearly_straight(self):
        for i in range(24):
            self.assertLessEqual(abs(scene_layout(scene(), i)["rotation"]),
                                 0.35)

    def test_blocks_rare_and_whisper_faint(self):
        # refs have no heavy blocks: at most one, very translucent
        for i in range(12):
            blocks = scene_layout(scene(), i)["blocks"]
            self.assertLessEqual(len(blocks), 1)
            for blk in blocks:
                r, g, b = blk["color"]
                self.assertLess(max(r, g, b) - min(r, g, b), 12)
                self.assertLessEqual(blk["alpha"], 70)

    def test_consecutive_scenes_differ_in_scale(self):
        widths = [scene_layout(scene(), i)["photo_w"] for i in range(6)]
        for a, b in zip(widths, widths[1:]):
            self.assertGreater(abs(a - b), 0.2)

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
