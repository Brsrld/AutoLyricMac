"""Unit tests for the pure alignment mapping (no model needed)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyrics.align import (align_lyrics, align_tokens, normalize_token,
                          tokenize_lines)


def asr(*triples):
    """Helper: (text, start, prob) -> word dicts with 0.3s duration."""
    return [{"text": t, "start": s, "end": s + 0.3, "prob": p}
            for t, s, p in triples]


class TestNormalization(unittest.TestCase):
    def test_case_punct_accents(self):
        self.assertEqual(normalize_token("Hold,"), "hold")
        self.assertEqual(normalize_token("don’t"), "dont")
        self.assertEqual(normalize_token("café!"), "cafe")
        self.assertEqual(normalize_token("—"), "")

    def test_tokenize_skips_empty(self):
        tokens = tokenize_lines(["Hold — me", ""])
        self.assertEqual([t.norm for t in tokens], ["hold", "me"])
        self.assertEqual([t.raw for t in tokens], ["Hold", "me"])


class TestAlignTokens(unittest.TestCase):
    def test_perfect_match(self):
        tokens = tokenize_lines(["hold me close"])
        mapped = align_tokens(tokens, asr(("Hold", 1.0, 0.9),
                                          ("me", 1.4, 0.8),
                                          ("close", 1.8, 0.95)))
        self.assertTrue(all(m["matched"] for m in mapped))
        self.assertAlmostEqual(mapped[0]["start"], 1.0)
        self.assertAlmostEqual(mapped[2]["confidence"], 0.95)

    def test_gap_interpolated_between_anchors(self):
        tokens = tokenize_lines(["hold me very close now"])
        # ASR missed "very close"
        mapped = align_tokens(tokens, asr(("hold", 1.0, 0.9),
                                          ("me", 1.4, 0.9),
                                          ("now", 4.0, 0.9)))
        very, close = mapped[2], mapped[3]
        self.assertFalse(very["matched"])
        self.assertLess(very["confidence"], 0.5)   # visibly uncertain
        self.assertGreaterEqual(very["start"], 1.7)
        self.assertLessEqual(close["end"], 4.0 + 1e-6)
        self.assertLess(very["start"], close["start"])  # ordered timing

    def test_leading_gap_left_untimed(self):
        tokens = tokenize_lines(["intro words here yes"])
        mapped = align_tokens(tokens, asr(("here", 5.0, 0.9), ("yes", 5.5, 0.9)))
        self.assertIsNone(mapped[0]["start"])
        self.assertEqual(mapped[0]["confidence"], 0.0)
        self.assertTrue(mapped[2]["matched"])

    def test_asr_extra_words_ignored(self):
        tokens = tokenize_lines(["hold me"])
        mapped = align_tokens(tokens, asr(("uh", 0.2, 0.3), ("hold", 1.0, 0.9),
                                          ("hmm", 1.2, 0.2), ("me", 1.4, 0.9)))
        self.assertTrue(all(m["matched"] for m in mapped))


class TestAlignLyrics(unittest.TestCase):
    def test_line_summaries_and_ratios(self):
        lines = ["hold me close", "words nobody sang"]
        aligned, matched_ratio, mean_conf = align_lyrics(
            lines, asr(("hold", 1.0, 0.9), ("me", 1.4, 0.8), ("close", 1.8, 1.0)))
        self.assertAlmostEqual(aligned[0]["start"], 1.0)
        self.assertAlmostEqual(aligned[0]["end"], 2.1)
        self.assertGreater(aligned[0]["confidence"], 0.8)
        # unsung line: no timing, zero confidence -> must surface as uncertain
        self.assertIsNone(aligned[1]["start"])
        self.assertEqual(aligned[1]["confidence"], 0.0)
        self.assertAlmostEqual(matched_ratio, 0.5)
        self.assertLess(mean_conf, 0.5)

    def test_word_payload_uses_raw_text(self):
        aligned, _, _ = align_lyrics(["Hold, me!"], asr(("hold", 1.0, 0.9),
                                                        ("me", 1.5, 0.9)))
        self.assertEqual([w["text"] for w in aligned[0]["words"]],
                         ["Hold,", "me!"])

    def test_lrc_fallback_rescues_low_confidence_lines(self):
        from lyrics.align import merge_lrc_fallback
        aligned, _, _ = align_lyrics(["hold me close", "words nobody sang"],
                                     asr(("hold", 1.0, 0.9), ("me", 1.4, 0.8),
                                         ("close", 1.8, 1.0)))
        rescued = merge_lrc_fallback(aligned, {1: (10.0, 13.0)})
        self.assertEqual(rescued, 1)
        self.assertAlmostEqual(aligned[1]["start"], 10.0)
        self.assertAlmostEqual(aligned[1]["end"], 13.0)
        self.assertEqual(aligned[1]["confidence"], 0.6)
        self.assertTrue(all(w["start"] is not None
                            for w in aligned[1]["words"]))
        # the confidently-matched line is untouched
        self.assertGreater(aligned[0]["confidence"], 0.8)
        self.assertAlmostEqual(aligned[0]["start"], 1.0)

    def test_lrc_fallback_ignores_lines_without_seed(self):
        from lyrics.align import merge_lrc_fallback
        aligned, _, _ = align_lyrics(["never sung"], [])
        self.assertEqual(merge_lrc_fallback(aligned, {}), 0)
        self.assertIsNone(aligned[0]["start"])

    def test_empty_inputs(self):
        aligned, ratio, conf = align_lyrics([], [])
        self.assertEqual(aligned, [])
        self.assertEqual(ratio, 0.0)
        aligned, ratio, conf = align_lyrics(["la la"], [])
        self.assertEqual(ratio, 0.0)
        self.assertIsNone(aligned[0]["start"])


class TestLrcWholesaleAndMonotonic(unittest.TestCase):
    """Weak/scrambled ASR must not corrupt a clean synced LRC."""

    def test_is_monotonic_detects_backward_jump(self):
        from lyrics.align import is_monotonic
        good = [{"start": 1.0}, {"start": 2.0}, {"start": None},
                {"start": 3.0}]
        bad = [{"start": 56.0}, {"start": 24.0}, {"start": 30.0}]
        self.assertTrue(is_monotonic(good))
        self.assertFalse(is_monotonic(bad))

    def test_align_from_lrc_is_monotonic_and_spreads_words(self):
        from lyrics.align import align_from_lrc, is_monotonic
        texts = ["first line here", "second", "third line"]
        spans = {0: (10.0, 13.0), 1: (13.0, 15.0), 2: (15.0, 18.0)}
        aligned, cov, conf = align_from_lrc(texts, spans)
        self.assertEqual(cov, 1.0)
        self.assertTrue(is_monotonic(aligned))
        w = aligned[0]["words"]
        self.assertEqual(len(w), 3)
        self.assertLess(w[0]["start"], w[1]["start"])   # words spread in order
        self.assertAlmostEqual(aligned[0]["start"], 10.0)

    def test_line_without_span_stays_untimed(self):
        from lyrics.align import align_from_lrc
        aligned, cov, _ = align_from_lrc(["a b", "c d"], {0: (1.0, 2.0)})
        self.assertIsNone(aligned[1]["start"])
        self.assertEqual(cov, 0.5)


if __name__ == "__main__":
    unittest.main()
