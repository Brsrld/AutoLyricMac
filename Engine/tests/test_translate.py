"""Unit tests for automatic Turkish translation (injected translator)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyrics.models import LyricsCandidate
from lyrics.store import LyricsStore
from lyrics.translate import fill_missing_translations

JOB = "a" * 32


class TestFillMissingTranslations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LyricsStore(Path(self.tmp.name) / "lyrics.db")
        self.store.save_lyrics(JOB, LyricsCandidate(
            provider="test", title="T", artist="A",
            plain_text="hold me close\nwe were young\nla la la"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_translates_untranslated_lines(self):
        fake = lambda text, f, t: f"TR({text})"
        translated, skipped = fill_missing_translations(
            self.store, JOB, "en", translator=fake)
        self.assertEqual(translated, 3)
        lines = self.store.get_lyrics(JOB)["lines"]
        self.assertEqual(lines[0]["translation"], "TR(hold me close)")

    def test_user_translations_never_overwritten(self):
        self.store.update_line(JOB, 1, translation="benim çevirim")
        fake = lambda text, f, t: f"TR({text})"
        translated, skipped = fill_missing_translations(
            self.store, JOB, "en", translator=fake)
        self.assertEqual(translated, 2)
        self.assertEqual(self.store.get_lyrics(JOB)["lines"][1]["translation"],
                         "benim çevirim")

    def test_turkish_source_skips_entirely(self):
        translated, skipped = fill_missing_translations(
            self.store, JOB, "tr", translator=lambda *a: "X")
        self.assertEqual(translated, 0)
        self.assertIsNone(self.store.get_lyrics(JOB)["lines"][0]["translation"])

    def test_failures_and_identity_results_skip_line(self):
        def flaky(text, f, t):
            if "young" in text:
                raise RuntimeError("model missing")
            if "la la" in text:
                return text          # untranslatable -> unchanged
            return "TR"
        translated, skipped = fill_missing_translations(
            self.store, JOB, "en", translator=flaky)
        self.assertEqual(translated, 1)
        self.assertEqual(skipped, 2)

    def test_looks_turkish_heuristic(self):
        from lyrics.translate import looks_turkish
        self.assertTrue(looks_turkish(["Şifa istemem balından",
                                       "Gönlüm seni unutmaz"]))
        self.assertTrue(looks_turkish(["ben sana bir sey diyecegim",
                                       "ama sen bana gelme simdi"]))
        self.assertFalse(looks_turkish(["I tried so hard and got so far",
                                        "But in the end it does not matter"]))
        self.assertFalse(looks_turkish([]))

    def test_missing_job_is_noop(self):
        translated, skipped = fill_missing_translations(
            self.store, "b" * 32, "en", translator=lambda *a: "X")
        self.assertEqual((translated, skipped), (0, 0))


if __name__ == "__main__":
    unittest.main()
