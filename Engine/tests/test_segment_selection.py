"""Unit tests for segment selection (pure logic, synthetic analysis data)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.audio_analysis import select_segment


def synthetic_analysis(duration=180.0, hop=0.5, loud_start=60.0, loud_end=105.0):
    """Quiet track with one loud, onset-dense, repeated 'chorus' region."""
    n = int(duration / hop)
    energy = []
    for i in range(n):
        t = i * hop
        energy.append(0.9 if loud_start <= t < loud_end else 0.2)
    onsets = []
    t = 0.0
    while t < duration:
        onsets.append(round(t, 2))
        t += 1.0 if loud_start <= t < loud_end else 4.0
    beats = [round(b * 0.5, 2) for b in range(int(duration * 2))]  # 120 BPM
    sections = [0.0, 30.0, loud_start, loud_end, 140.0]
    repetition = [0.2, 0.3, 1.0, 0.4, 0.2]
    return {
        "duration": duration,
        "tempo_bpm": 120.0,
        "beats": beats,
        "onsets": onsets,
        "energy_hop_seconds": hop,
        "energy": energy,
        "sections": sections,
        "section_repetition": repetition,
    }


class TestSelectSegment(unittest.TestCase):
    def test_picks_the_loud_repeated_region(self):
        choice = select_segment(synthetic_analysis(), 45)
        self.assertAlmostEqual(choice.end - choice.start, 45.0, places=3)
        # the 45s window should start at (or very near) the chorus boundary
        self.assertTrue(55.0 <= choice.start <= 65.0,
                        f"start {choice.start} not near the loud region")
        self.assertTrue(choice.reasons)

    def test_exact_requested_length_for_all_durations(self):
        for target in (30, 45, 60):
            choice = select_segment(synthetic_analysis(), target)
            self.assertAlmostEqual(choice.end - choice.start, target, places=3)

    def test_never_exceeds_track_end(self):
        choice = select_segment(synthetic_analysis(duration=70.0,
                                                   loud_start=50.0,
                                                   loud_end=70.0), 60)
        self.assertLessEqual(choice.end, 70.0 + 1e-6)
        self.assertGreaterEqual(choice.start, 0.0)

    def test_short_track_uses_whole_track(self):
        choice = select_segment(synthetic_analysis(duration=25.0), 30)
        self.assertEqual(choice.start, 0.0)
        self.assertAlmostEqual(choice.end, 25.0, places=3)
        self.assertIn("whole track", choice.reasons[0])

    def test_manual_override_wins(self):
        choice = select_segment(synthetic_analysis(), 30, start_override=10.0)
        self.assertAlmostEqual(choice.start, 10.0, delta=0.4)  # may snap to beat
        self.assertAlmostEqual(choice.end - choice.start, 30.0, places=3)
        self.assertIn("override", choice.reasons[0].lower())

    def test_override_clamped_to_track(self):
        choice = select_segment(synthetic_analysis(duration=100.0), 30,
                                start_override=95.0)
        self.assertLessEqual(choice.end, 100.0 + 1e-6)

    def test_start_snaps_to_beat(self):
        choice = select_segment(synthetic_analysis(), 45)
        beats = [round(b * 0.5, 2) for b in range(360)]
        self.assertTrue(any(abs(choice.start - b) < 0.01 for b in beats),
                        f"start {choice.start} is not on a beat")

    def test_deterministic(self):
        a = select_segment(synthetic_analysis(), 45)
        b = select_segment(synthetic_analysis(), 45)
        self.assertEqual((a.start, a.end, a.score), (b.start, b.end, b.score))


if __name__ == "__main__":
    unittest.main()
