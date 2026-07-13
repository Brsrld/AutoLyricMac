"""Unit tests for the Archive Collage pure layout rules (Phase 5)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "render"))

from archive_renderer import photo_screen_rect, scene_layout
from subtitles.layout import SAFE_ZONE


def scene(motion_type="slow_push", amount=0.06, band="calm"):
    return {"motion": {"type": motion_type, "amount": amount,
                       "pulse_beats": []}, "energy_band": band}


class TestSceneLayout(unittest.TestCase):
    def test_single_image_scenes_alternate_full_and_panel(self):
        # the reference full/panel rhythm applies when a scene has 1 image
        for i in range(0, 24):
            layout = scene_layout(scene(), i)
            if layout["extras"]:
                continue
            if i % 2 == 0:
                self.assertGreaterEqual(layout["photo_w"], 0.84)
            else:
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

    def test_composition_varies_between_scenes(self):
        specs = [(round(scene_layout(scene(), i)["photo_w"], 2),
                  len(scene_layout(scene(), i)["extras"]))
                 for i in range(6)]
        self.assertGreater(len(set(specs)), 3)

    def test_scenes_show_one_to_three_images(self):
        counts = set()
        for i in range(24):
            layout = scene_layout(scene(), i)
            n = 1 + len(layout["extras"])
            self.assertTrue(1 <= n <= 3)
            counts.add(n)
            if layout["extras"]:
                self.assertLessEqual(layout["photo_w"], 0.72)
                for extra in layout["extras"]:
                    self.assertTrue(0.2 <= extra["w"] <= 0.45)
        self.assertGreater(len(counts), 1, "count must actually vary")
        # deterministic per scene index
        self.assertEqual(len(scene_layout(scene(), 5)["extras"]),
                         len(scene_layout(scene(), 5)["extras"]))

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
