"""Unit tests for the lyrics module: LRC parsing, ranking, providers (mocked),
and the SQLite store (corrections/translations persist)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyrics.lrc import infer_line_ends, parse_lrc, plain_lines
from lyrics.models import LyricsCandidate
from lyrics.providers import LocalFileProvider, LRCLIBProvider
from lyrics.ranking import normalize_title, rank_candidates, score_candidate
from lyrics.store import LyricsStore

SAMPLE_LRC = """\
[ar:Sample Artist]
[ti:Sample Song]
[offset:+500]
[00:12.30]Hold me close under the light
[00:18.10][01:02.00]We were young, we were bright
[00:25.50]<00:25.50>Every <00:26.10>word <00:26.60>counted
Some untagged credit line
"""


class TestLrcParsing(unittest.TestCase):
    def test_metadata_and_line_count(self):
        meta, lines = parse_lrc(SAMPLE_LRC)
        self.assertEqual(meta["ar"], "Sample Artist")
        # 1 + 2 (repeated tag) + 1 = 4 timed lines; credit line dropped
        self.assertEqual(len(lines), 4)

    def test_offset_shifts_earlier(self):
        _, lines = parse_lrc(SAMPLE_LRC)
        self.assertAlmostEqual(lines[0].start, 12.30 - 0.5, places=3)

    def test_repeated_tags_emit_two_lines(self):
        _, lines = parse_lrc(SAMPLE_LRC)
        texts = [l.text for l in lines]
        self.assertEqual(texts.count("We were young, we were bright"), 2)

    def test_enhanced_word_tags(self):
        _, lines = parse_lrc(SAMPLE_LRC)
        worded = [l for l in lines if l.words]
        self.assertEqual(len(worded), 1)
        self.assertEqual([w.text for w in worded[0].words],
                         ["Every", "word", "counted"])
        self.assertAlmostEqual(worded[0].words[1].start, 26.10 - 0.5, places=3)
        self.assertEqual(worded[0].text, "Every word counted")

    def test_infer_line_ends_caps_hold_and_orders(self):
        _, lines = parse_lrc(SAMPLE_LRC)
        spans = infer_line_ends(lines, track_duration=120.0)
        for (s, e), line in zip(spans, lines):
            self.assertGreater(e, s)
            self.assertLessEqual(e - s, 8.0)
        # sorted by time despite the repeated later tag
        self.assertEqual([round(l.start, 2) for l in lines],
                         sorted(round(l.start, 2) for l in lines))

    def test_plain_lines(self):
        self.assertEqual(plain_lines("a\n\n  b \n"), ["a", "b"])

    def test_garbage_is_safe(self):
        meta, lines = parse_lrc("not lrc at all\n[[]weird")
        self.assertEqual(lines, [])


class TestRanking(unittest.TestCase):
    def make(self, **kw):
        base = dict(provider="test", title="Hold Me Close", artist="Sample Artist",
                    duration=210.0, plain_text="x" * 200)
        base.update(kw)
        return LyricsCandidate(**base)

    def test_normalize_strips_noise(self):
        self.assertEqual(normalize_title("Hold Me Close (Official Video) [HD]"),
                         "hold me close")

    def test_right_song_beats_wrong_synced_song(self):
        right = self.make()
        wrong = self.make(title="Completely Different Song",
                          artist="Another Band", lrc_text="[00:01.00]x" * 40)
        ranked = rank_candidates([wrong, right], "Sample Artist",
                                 "Hold Me Close", 210.0)
        self.assertEqual(ranked[0].candidate.title, "Hold Me Close")

    def test_synced_wins_among_equals(self):
        plain = self.make()
        synced = self.make(lrc_text="[00:01.00]line\n" * 40)
        ranked = rank_candidates([plain, synced], "Sample Artist",
                                 "Hold Me Close", 210.0)
        self.assertTrue(ranked[0].candidate.synced)

    def test_duration_mismatch_penalized(self):
        close = self.make(duration=212.0)
        far = self.make(duration=300.0)
        s_close, _ = score_candidate(close, "Sample Artist", "Hold Me Close", 210.0)
        s_far, _ = score_candidate(far, "Sample Artist", "Hold Me Close", 210.0)
        self.assertGreater(s_close, s_far)

    def test_instrumental_and_hopeless_dropped(self):
        instrumental = self.make(instrumental=True, plain_text="")
        unrelated = self.make(title="zzz", artist="qqq", duration=999.0)
        ranked = rank_candidates([instrumental, unrelated], "Sample Artist",
                                 "Hold Me Close", 210.0)
        self.assertEqual(ranked, [])


class TestLRCLIBProviderMocked(unittest.TestCase):
    def test_search_maps_fields_and_dedupes(self):
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if "/get?" in url:
                return {"id": 7, "trackName": "Hold Me Close",
                        "artistName": "Sample Artist", "albumName": "LP",
                        "duration": 210.0, "plainLyrics": "line one\nline two",
                        "syncedLyrics": "[00:01.00]line one"}
            return [
                {"id": 7, "trackName": "Hold Me Close",
                 "artistName": "Sample Artist", "plainLyrics": "dup"},
                {"id": 9, "trackName": "Hold Me Close (live)",
                 "artistName": "Sample Artist", "plainLyrics": "live take"},
                {"id": 10, "instrumental": True, "trackName": "Hold Me Close",
                 "artistName": "Sample Artist"},
                {"id": 11, "trackName": "Empty", "artistName": "Nobody"},
            ]

        provider = LRCLIBProvider(opener=fake_fetch)
        results = provider.search("Sample Artist", "Hold Me Close",
                                  duration=210.0)
        refs = [c.provider_ref for c in results]
        self.assertEqual(refs, ["7", "9", "10"])  # dedup + empty dropped
        self.assertTrue(results[0].synced)
        self.assertTrue(results[2].instrumental)
        # 1 exact /get + 2 cleaned /search queries (combo + title-only)
        self.assertEqual(len(calls), 3)

    def test_get_404_falls_through_to_search(self):
        provider = LRCLIBProvider(
            opener=lambda url: None if "/get?" in url else [])
        self.assertEqual(provider.search("A", "B", duration=100.0), [])


class TestLocalFileProvider(unittest.TestCase):
    def test_reads_lrc_and_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Sample Artist - Hold Me Close.lrc").write_text(
                "[00:01.00]hello", encoding="utf-8")
            (d / "notes.txt").write_text("plain lyrics here", encoding="utf-8")
            (d / "ignored.pdf").write_text("x", encoding="utf-8")
            results = LocalFileProvider([d]).search("", "")
            self.assertEqual(len(results), 2)
            lrc = next(c for c in results if c.synced)
            self.assertEqual(lrc.artist, "Sample Artist")
            self.assertEqual(lrc.title, "Hold Me Close")
            txt = next(c for c in results if not c.synced)
            self.assertEqual(txt.title, "notes")


class TestLyricsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LyricsStore(Path(self.tmp.name) / "lyrics.db")
        self.job = "a" * 32

    def tearDown(self):
        self.tmp.cleanup()

    def synced_candidate(self):
        return LyricsCandidate(
            provider="lrclib", provider_ref="7", artist="A", title="T",
            duration=100.0, plain_text="one two\nthree four",
            lrc_text="[00:10.00]one two\n[00:15.00]three four")

    def test_save_and_get_synced(self):
        self.store.save_lyrics(self.job, self.synced_candidate(), score=0.9,
                               track_duration=100.0)
        payload = self.store.get_lyrics(self.job)
        self.assertTrue(payload["synced"])
        self.assertEqual(len(payload["lines"]), 2)
        self.assertAlmostEqual(payload["lines"][0]["start"], 10.0)
        self.assertIsNone(payload["lines"][0]["confidence"])
        self.assertFalse(payload["suspect"])

    def test_corrections_and_translations_persist(self):
        self.store.save_lyrics(self.job, self.synced_candidate())
        self.assertTrue(self.store.update_line(
            self.job, 0, corrected_text="one too", translation="bir de"))
        # reopen from disk to prove persistence
        reopened = LyricsStore(self.store.db_path)
        line = reopened.get_lyrics(self.job)["lines"][0]
        self.assertEqual(line["display_text"], "one too")
        self.assertEqual(line["corrected_text"], "one too")
        self.assertEqual(line["translation"], "bir de")
        # clearing the correction reverts to canonical text
        reopened.update_line(self.job, 0, corrected_text="")
        line = reopened.get_lyrics(self.job)["lines"][0]
        self.assertEqual(line["display_text"], "one two")

    def test_refetch_replaces_lyrics(self):
        self.store.save_lyrics(self.job, self.synced_candidate())
        other = LyricsCandidate(provider="lrclib", provider_ref="8",
                                artist="A", title="T2", plain_text="only line")
        self.store.save_lyrics(self.job, other)
        payload = self.store.get_lyrics(self.job)
        self.assertEqual(payload["title"], "T2")
        self.assertEqual(len(payload["lines"]), 1)
        self.assertFalse(payload["synced"])

    def test_alignment_and_uncertainty_flags(self):
        self.store.save_lyrics(self.job, self.synced_candidate())
        self.store.apply_alignment(self.job, [
            {"line_index": 0, "start": 10.2, "end": 12.0, "confidence": 0.92,
             "words": [{"text": "one", "start": 10.2, "end": 10.6,
                        "confidence": 0.95},
                       {"text": "two", "start": 10.7, "end": 12.0,
                        "confidence": 0.9}]},
            {"line_index": 1, "start": None, "end": None, "confidence": 0.1,
             "words": []},
        ], matched_ratio=0.5, mean_confidence=0.51)
        payload = self.store.get_lyrics(self.job)
        self.assertTrue(payload["aligned"])
        self.assertFalse(payload["lines"][0]["uncertain"])
        self.assertTrue(payload["lines"][1]["uncertain"])
        self.assertEqual(len(payload["lines"][0]["words"]), 2)

    def test_suspect_flag_when_alignment_poor(self):
        self.store.save_lyrics(self.job, self.synced_candidate())
        self.store.apply_alignment(self.job, [], matched_ratio=0.1,
                                   mean_confidence=0.12)
        self.assertTrue(self.store.get_lyrics(self.job)["suspect"])

    def test_missing_job_returns_none(self):
        self.assertIsNone(self.store.get_lyrics("b" * 32))

    def test_search_cache_roundtrip(self):
        cands = [self.synced_candidate()]
        self.store.store_search("k", cands)
        cached = self.store.cached_search("k")
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].provider_ref, "7")
        self.assertTrue(cached[0].synced)
        self.assertIsNone(self.store.cached_search("k", ttl=-1))


class TestTitleCleaning(unittest.TestCase):
    def test_strips_youtube_noise(self):
        from lyrics.providers import clean_track_name
        self.assertEqual(clean_track_name(
            'Ya Sidi (Clip Officiel "Marseille") [4K]'), "Ya Sidi")
        self.assertEqual(clean_track_name(
            "In The End [Official HD Music Video]"), "In The End")
        self.assertEqual(clean_track_name(
            "Numb (Official Music Video) [4K UPGRADE]"), "Numb")
        self.assertEqual(clean_track_name(
            "Wake Me Up (Official Lyric Video) | Avicii"), "Wake Me Up")
        self.assertEqual(clean_track_name(
            "Shot Me Down feat. Skylar Grey"), "Shot Me Down")

    def test_split_artist_title(self):
        from lyrics.providers import split_artist_title
        self.assertEqual(split_artist_title("Orange Blossom - Ya Sidi"),
                         ("Orange Blossom", "Ya Sidi"))
        self.assertEqual(split_artist_title("Just A Title"),
                         ("", "Just A Title"))


if __name__ == "__main__":
    unittest.main()
