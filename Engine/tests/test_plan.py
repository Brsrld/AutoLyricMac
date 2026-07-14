"""Unit tests for semantic extraction and the deterministic scene planner."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plan.planner import build_scene_plan, recommend_style
from plan.semantic import dominant_emotion, extract_semantics


class TestSemantics(unittest.TestCase):
    def test_english_line(self):
        sem = extract_semantics("Hold me close under the light")
        self.assertIn("embrace", sem["subjects"])
        self.assertIn("light", sem["subjects"])
        self.assertGreater(sem["emotions"]["love"], 0)
        self.assertTrue(sem["queries"])

    def test_turkish_line_with_suffixes(self):
        sem = extract_semantics("Yalnız gecelerde yollarda hasretim")
        self.assertIn("solitude", sem["subjects"])
        self.assertIn("night", sem["subjects"])
        self.assertIn("road", sem["subjects"])
        self.assertGreater(sem["emotions"]["loneliness"], 0)
        self.assertGreater(sem["emotions"]["longing"], 0)

    def test_english_plural(self):
        sem = extract_semantics("counting stars through windows")
        self.assertIn("stars", sem["subjects"])
        self.assertIn("window", sem["subjects"])

    def test_no_match_gets_generic_queries(self):
        sem = extract_semantics("qwzx bnmp vvv")
        self.assertEqual(sem["subjects"], [])
        self.assertTrue(sem["queries"])
        self.assertEqual(dominant_emotion(sem["emotions"]), "neutral")

    def test_deterministic(self):
        a = extract_semantics("rain on my window")
        b = extract_semantics("rain on my window")
        self.assertEqual(a, b)


class TestRecommendStyle(unittest.TestCase):
    def test_melancholy_gets_archive(self):
        style, conf, reason = recommend_style(
            {"melancholy": 3, "longing": 2, "joy": 0.5}, 90)
        self.assertEqual(style, "archiveCollage")
        self.assertGreater(conf, 0.5)

    def test_warm_domestic_gets_doodle(self):
        style, _, _ = recommend_style({"love": 3, "joy": 2, "calm": 1}, 110)
        self.assertEqual(style, "doodleMemory")

    def test_no_signal_defaults_archive(self):
        style, conf, _ = recommend_style({}, 100)
        self.assertEqual(style, "archiveCollage")
        self.assertEqual(conf, 0.0)


def make_analysis(duration=60.0, hop=0.5, loud=(20.0, 40.0)):
    n = int(duration / hop)
    energy = [0.9 if loud[0] <= i * hop < loud[1] else 0.3 for i in range(n)]
    return {
        "duration": duration,
        "tempo_bpm": 120.0,
        "beats": [round(b * 0.5, 2) for b in range(int(duration * 2))],
        "energy_hop_seconds": hop,
        "energy": energy,
        "sections": [0.0, 20.0, 40.0],
        "section_repetition": [0.3, 1.0, 0.3],
    }


def make_lines():
    texts = [
        ("Hold me close under the light", 2.0, 6.0),
        ("We were young and we were bright", 7.0, 11.0),
        ("Rain on the window tonight", 22.0, 26.0),
        ("Dancing in the kitchen light", 27.0, 31.0),
    ]
    return [{"display_text": t, "translation": None, "start": s, "end": e,
             "confidence": 0.9, "uncertain": False} for t, s, e in texts]


class TestScenePlan(unittest.TestCase):
    def plan(self, style="archiveCollage", start=0.0, end=45.0):
        return build_scene_plan(make_lines(), make_analysis(), style,
                                start, end)

    def test_scenes_cover_segment_without_overlap(self):
        plan = self.plan()
        scenes = plan["scenes"]
        self.assertAlmostEqual(scenes[0]["start"], 0.0)
        self.assertAlmostEqual(scenes[-1]["end"], 45.0, places=2)
        for a, b in zip(scenes, scenes[1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=3)

    def test_scene_per_phrase_not_per_beat(self):
        plan = self.plan()
        # 4 lyric lines + ambient gaps; far fewer scenes than the 90 beats
        self.assertEqual(plan["lyric_scene_count"], 4)
        self.assertLess(plan["scene_count"], 12)
        # beats only appear as micro-motion pulses
        self.assertTrue(any(s["motion"]["pulse_beats"] for s in plan["scenes"]))

    def test_lyric_scenes_carry_semantics_and_queries(self):
        plan = self.plan()
        lyric_scenes = [s for s in plan["scenes"] if s["lyric"]]
        for s in lyric_scenes:
            self.assertTrue(s["queries"], s["lyric"])
            self.assertNotEqual(s["emotion"], "")
        rain = next(s for s in lyric_scenes if "Rain" in s["lyric"])
        self.assertIn("rain", rain["subjects"])

    def test_energy_shortens_transitions_and_scales_motion(self):
        plan = self.plan()
        loud = [s for s in plan["scenes"] if s["energy_band"] == "energetic"]
        quiet = [s for s in plan["scenes"] if s["energy_band"] == "calm"]
        self.assertTrue(loud and quiet)
        self.assertGreater(min(s["motion"]["amount"] for s in loud),
                           max(s["motion"]["amount"] for s in quiet))

    def test_ambient_gaps_become_scenes_capped_in_length(self):
        plan = self.plan()
        ambient = [s for s in plan["scenes"] if s["lyric"] is None]
        self.assertTrue(ambient)
        for s in ambient:
            self.assertLessEqual(s["duration"], 8.0)

    def test_transition_types_match_style(self):
        for style, allowed in (("archiveCollage",
                                {"crossfade", "fade_white", "fade_dark",
                                 "block_wipe", "layered_dissolve"}),
                               ("doodleMemory",
                                {"cut", "short_dissolve", "paper_wipe",
                                 "sticker_pop"})):
            plan = self.plan(style=style)
            for s in plan["scenes"]:
                self.assertIn(s["transition"]["type"], allowed)

    def test_automatic_style_resolves_to_recommendation(self):
        plan = self.plan(style="automatic")
        self.assertIn(plan["style"],
                      ("archiveCollage", "doodleMemory"))
        self.assertEqual(plan["style"], plan["recommended_style"])

    def test_deterministic(self):
        self.assertEqual(self.plan(), self.plan())

    def test_no_lines_yields_ambient_plan(self):
        plan = build_scene_plan([], make_analysis(), "archiveCollage", 0, 30)
        self.assertGreaterEqual(plan["scene_count"], 1)
        self.assertEqual(plan["lyric_scene_count"], 0)

    def test_ambient_and_unmatched_scenes_use_song_context(self):
        plan = build_scene_plan(make_lines(), make_analysis(),
                                "archiveCollage", 0, 45,
                                title_hint="Rainy Night Memories")
        ambient = [s for s in plan["scenes"] if s["lyric"] is None]
        self.assertTrue(ambient)
        for s in ambient:
            self.assertTrue(s["queries"], "ambient scenes must have queries")
            joined = " ".join(s["queries"])
            self.assertNotIn("abstract light texture", joined,
                             "song context must replace generic textures")
        # title semantics (rain/night/memory) should surface somewhere
        all_q = " ".join(q for s in ambient for q in s["queries"])
        self.assertTrue(any(k in all_q for k in ("rain", "night", "photo",
                                                 "memor", "vintage")))

    def test_unmatched_lyric_line_gets_song_queries(self):
        lines = [{"display_text": "qwzx bnmp vvv", "translation": None,
                  "start": 2.0, "end": 6.0, "confidence": 0.9,
                  "uncertain": False}]
        plan = build_scene_plan(lines, make_analysis(), "archiveCollage",
                                0, 30, title_hint="Lonely Winter Road")
        scene = next(s for s in plan["scenes"] if s["lyric"])
        joined = " ".join(scene["queries"])
        self.assertTrue(any(k in joined for k in ("lone", "winter", "road",
                                                  "solitary", "empty")),
                        joined)

    def test_untimed_lines_are_ignored(self):
        lines = make_lines() + [{"display_text": "ghost", "translation": None,
                                 "start": None, "end": None,
                                 "confidence": 0.0, "uncertain": True}]
        plan = build_scene_plan(lines, make_analysis(), "archiveCollage", 0, 45)
        self.assertEqual(plan["lyric_scene_count"], 4)


class TestVocalGating(unittest.TestCase):
    """Lines the LRC placed over an instrumental section are suppressed."""

    def _lines(self):
        return [{"display_text": t, "translation": None, "start": st,
                 "end": e, "confidence": 0.9, "uncertain": False}
                for t, st, e in [("first line", 5.0, 9.0),
                                 ("instrumental line", 12.0, 16.0),
                                 ("last line", 20.0, 24.0)]]

    def test_no_vocal_flag_and_window(self):
        from plan.planner import build_scene_plan, _vocal_window
        # actual singing only 5-9 and 20-24; 12-16 is instrumental
        segs = [(5.0, 9.0), (20.0, 24.0)]
        self.assertIsNone(_vocal_window(12.0, 16.0, segs))
        plan = build_scene_plan(self._lines(), make_analysis(),
                                "archiveCollage", 0.0, 30.0,
                                vocal_segments=segs)
        by_lyric = {s["lyric"]: s for s in plan["scenes"] if s["lyric"]}
        self.assertTrue(by_lyric["instrumental line"]["no_vocal"])
        self.assertFalse(by_lyric["first line"]["no_vocal"])
        self.assertFalse(by_lyric["last line"]["no_vocal"])

    def test_no_segments_means_all_shown(self):
        from plan.planner import build_scene_plan
        plan = build_scene_plan(self._lines(), make_analysis(),
                                "archiveCollage", 0.0, 30.0)
        self.assertFalse(any(s.get("no_vocal") for s in plan["scenes"]))


if __name__ == "__main__":
    unittest.main()
