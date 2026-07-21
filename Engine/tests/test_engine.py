"""Unit tests for the engine's pure logic: URL validation, metadata
mapping, error classification, and safe path generation."""

import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (
    build_metadata,
    classify_ytdlp_error,
    job_dir_for,
    new_job_id,
    validate_youtube_url,
)


class TestValidateYouTubeURL(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                         "dQw4w9WgXcQ")

    def test_short_link(self):
        self.assertEqual(validate_youtube_url("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_shorts(self):
        self.assertEqual(validate_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
                         "dQw4w9WgXcQ")

    def test_music(self):
        self.assertEqual(validate_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ"),
                         "dQw4w9WgXcQ")

    def test_extra_params(self):
        self.assertEqual(
            validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=X"),
            "dQw4w9WgXcQ")

    def test_whitespace_trimmed(self):
        self.assertEqual(validate_youtube_url("  https://youtu.be/dQw4w9WgXcQ \n"),
                         "dQw4w9WgXcQ")

    def test_invalid(self):
        for bad in [
            None, "", "not a url", "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://example.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch",
            "https://youtu.be/",
            "https://evilyoutube.com/watch?v=dQw4w9WgXcQ",
            "javascript:alert(1)",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ; rm -rf /",
        ]:
            self.assertIsNone(validate_youtube_url(bad), f"should reject: {bad!r}")

    def test_rejects_oversized(self):
        self.assertIsNone(validate_youtube_url("https://youtu.be/" + "a" * 3000))


class TestBuildMetadata(unittest.TestCase):
    def test_full_info(self):
        info = {"id": "dQw4w9WgXcQ", "title": "Song", "uploader": "Artist",
                "duration": 212, "thumbnail": "https://i.ytimg.com/x.jpg"}
        meta = build_metadata(info, "https://youtu.be/dQw4w9WgXcQ")
        self.assertTrue(meta["valid"])
        self.assertEqual(meta["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(meta["title"], "Song")
        self.assertEqual(meta["uploader"], "Artist")
        self.assertEqual(meta["duration"], 212)
        self.assertEqual(meta["thumbnail_url"], "https://i.ytimg.com/x.jpg")
        self.assertEqual(meta["original_url"], "https://youtu.be/dQw4w9WgXcQ")

    def test_falls_back_to_channel(self):
        meta = build_metadata({"id": "x", "channel": "Chan"}, "u")
        self.assertEqual(meta["uploader"], "Chan")

    def test_missing_fields_are_none(self):
        meta = build_metadata({}, "u")
        self.assertTrue(meta["valid"])
        for key in ("video_id", "title", "uploader", "duration", "thumbnail_url"):
            self.assertIsNone(meta[key])


class TestClassifyError(unittest.TestCase):
    def test_age_restricted(self):
        code, _ = classify_ytdlp_error("ERROR: Sign in to confirm your age")
        self.assertEqual(code, "restricted")

    def test_region(self):
        code, _ = classify_ytdlp_error("The uploader has not made this video available in your country")
        self.assertEqual(code, "restricted")

    def test_unavailable(self):
        code, _ = classify_ytdlp_error("ERROR: Video unavailable")
        self.assertEqual(code, "unavailable")

    def test_private(self):
        code, _ = classify_ytdlp_error("ERROR: Private video. Sign in if you've been granted access")
        self.assertEqual(code, "unavailable")

    def test_network(self):
        code, _ = classify_ytdlp_error("urlopen error: connection timed out")
        self.assertEqual(code, "network")

    def test_unsupported(self):
        code, _ = classify_ytdlp_error("Unsupported URL: https://example.com")
        self.assertEqual(code, "invalid_url")

    def test_fallback(self):
        code, msg = classify_ytdlp_error("something exotic happened")
        self.assertEqual(code, "ytdlp_failed")
        self.assertIn("something exotic happened", msg)


class TestSafePaths(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())

    def test_valid_job_id(self):
        job_id = new_job_id()
        path = job_dir_for(job_id, base_dir=self.base)
        self.assertEqual(path.parent, self.base.resolve())
        self.assertEqual(path.name, job_id)

    def test_generated_ids_are_hex32(self):
        for _ in range(10):
            job_id = new_job_id()
            self.assertRegex(job_id, r"^[0-9a-f]{32}$")

    def test_rejects_traversal_and_junk(self):
        for bad in ["../evil", "..", "a/b", "x" * 32, "", None,
                    uuid.uuid4().hex.upper(), "$(rm -rf /)", "job; echo hi",
                    uuid.uuid4().hex + "/.."]:
            with self.assertRaises(ValueError, msg=f"should reject: {bad!r}"):
                job_dir_for(bad, base_dir=self.base)


class TestDrawnMediaGuard(unittest.TestCase):
    """Photo styles must never show AI-drawn Doodle illustrations."""

    def test_drawn_doodle_asset_is_detected(self):
        from engine import is_drawn_media
        self.assertTrue(is_drawn_media(
            {"provider": "fal_ai", "file_path": "/c/media/x/drawn_3.jpg"}))

    def test_stock_and_photo_fallback_assets_pass(self):
        from engine import is_drawn_media
        self.assertFalse(is_drawn_media(None))
        self.assertFalse(is_drawn_media(
            {"provider": "pexels", "file_path": "/c/media/x/pexels_1.jpg"}))
        # photorealistic AI fallback (gen_*) is not a doodle drawing
        self.assertFalse(is_drawn_media(
            {"provider": "fal_ai", "file_path": "/c/media/x/gen_2.jpg"}))


class TestAudioName(unittest.TestCase):
    """Original-audio name stays clean and consistent for discoverability."""

    def test_song_and_artist_joined(self):
        from engine import _compose_audio_name
        self.assertEqual(_compose_audio_name("Ya Sîdî", "Orange Blossom"),
                         "Ya Sîdî — Orange Blossom")

    def test_artist_already_in_song_not_repeated(self):
        from engine import _compose_audio_name
        self.assertEqual(_compose_audio_name("Adele - Hello", "Adele"),
                         "Adele - Hello")

    def test_empty_artist_or_song(self):
        from engine import _compose_audio_name
        self.assertEqual(_compose_audio_name("Hello", ""), "Hello")
        self.assertEqual(_compose_audio_name("", "Adele"), "Adele")

    def test_capped_at_100(self):
        from engine import _compose_audio_name
        self.assertLessEqual(len(_compose_audio_name("s" * 80, "a" * 80)), 100)


class TestEmotionClean(unittest.TestCase):
    def test_known_and_freetext_and_junk(self):
        from engine import _clean_emotion
        self.assertEqual(_clean_emotion("Hope"), "hope")
        self.assertEqual(_clean_emotion("ISYAN"), "isyan")
        self.assertEqual(_clean_emotion("a!!b"), "ab")
        self.assertEqual(_clean_emotion("   "), "")


if __name__ == "__main__":
    unittest.main()
