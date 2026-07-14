"""Unit tests for the stock-media pipeline: provider parsing (mocked JSON),
fallback, ranking/rejection, perceptual dedup, attribution store, fetching."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from media.dedup import dhash, hamming, is_duplicate
from media.providers import (MediaCandidate, MediaProviderError,
                             PexelsProvider, PixabayProvider,
                             UnsplashProvider, build_providers, search_all)
from media.ranking import rank_media, reject_reason, score_media
from media.store import MediaStore, fetch_photo, pick_and_fetch

PEXELS_PHOTO_FIXTURE = {
    "photos": [{
        "id": 101, "width": 3000, "height": 4500,
        "url": "https://www.pexels.com/photo/101/",
        "photographer": "Ada", "photographer_url": "https://pexels.com/@ada",
        "alt": "rain drops on window glass",
        "src": {"original": "https://images.pexels.com/101.jpg",
                "large2x": "https://images.pexels.com/101-l.jpg",
                "medium": "https://images.pexels.com/101-m.jpg"},
    }],
}

PEXELS_VIDEO_FIXTURE = {
    "videos": [{
        "id": 202, "width": 1080, "height": 1920, "duration": 21,
        "url": "https://www.pexels.com/video/202/",
        "image": "https://images.pexels.com/v202.jpg",
        "user": {"name": "Ben", "url": "https://pexels.com/@ben"},
        "video_files": [
            {"link": "https://v.pexels.com/202-720.mp4", "width": 405, "height": 720},
            {"link": "https://v.pexels.com/202-1920.mp4", "width": 1080, "height": 1920},
        ],
    }],
}

PIXABAY_FIXTURE = {
    "hits": [{
        "id": 303, "imageWidth": 2000, "imageHeight": 3000,
        "pageURL": "https://pixabay.com/photos/303/",
        "largeImageURL": "https://cdn.pixabay.com/303.jpg",
        "previewURL": "https://cdn.pixabay.com/303-s.jpg",
        "user": "Cem", "user_id": 9, "tags": "window, rain, mood",
    }],
}

UNSPLASH_FIXTURE = {
    "results": [{
        "id": "u404", "width": 4000, "height": 6000,
        "alt_description": "person by rainy window",
        "description": None,
        "urls": {"raw": "https://images.unsplash.com/u404?raw",
                 "full": "https://images.unsplash.com/u404",
                 "small": "https://images.unsplash.com/u404-s"},
        "links": {"html": "https://unsplash.com/photos/u404"},
        "user": {"name": "Deniz", "links": {"html": "https://unsplash.com/@deniz"}},
    }],
}


class TestProviderParsing(unittest.TestCase):
    def test_pexels_photo(self):
        p = PexelsProvider("k", opener=lambda url: PEXELS_PHOTO_FIXTURE)
        [c] = p.search("rain window")
        self.assertEqual((c.provider, c.kind), ("pexels", "photo"))
        self.assertEqual(c.download_url, "https://images.pexels.com/101.jpg")
        self.assertEqual(c.creator, "Ada")
        self.assertEqual(c.license, "Pexels License")
        self.assertTrue(c.portrait)
        self.assertIn("rain", c.tags)

    def test_pexels_video_picks_1080_file(self):
        p = PexelsProvider("k", opener=lambda url: PEXELS_VIDEO_FIXTURE)
        [c] = p.search("rain", kind="video")
        self.assertEqual(c.kind, "video")
        self.assertEqual(c.download_url, "https://v.pexels.com/202-1920.mp4")
        self.assertEqual(c.duration, 21.0)

    def test_pixabay_photo(self):
        p = PixabayProvider("k", opener=lambda url: PIXABAY_FIXTURE)
        [c] = p.search("rain window")
        self.assertEqual(c.provider, "pixabay")
        self.assertEqual(c.creator, "Cem")
        self.assertIn("rain", c.tags)

    def test_unsplash_photo_and_no_video(self):
        p = UnsplashProvider("k", opener=lambda url: UNSPLASH_FIXTURE)
        [c] = p.search("rain window")
        self.assertEqual(c.provider, "unsplash")
        self.assertEqual(c.creator, "Deniz")
        self.assertEqual(p.search("rain", kind="video"), [])

    def test_build_providers_order_and_gaps(self):
        chain = build_providers({"pixabay": "b", "pexels": "a"})
        self.assertEqual([p.name for p in chain], ["pexels", "pixabay"])
        self.assertEqual(build_providers({}), [])


class TestSearchAllFallback(unittest.TestCase):
    def test_failing_provider_is_skipped(self):
        broken = PexelsProvider("bad", opener=lambda url: (_ for _ in ()).throw(
            MediaProviderError("API key rejected")))
        good = PixabayProvider("k", opener=lambda url: PIXABAY_FIXTURE)
        candidates, errors = search_all([broken, good], ["rain window"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider, "pixabay")
        self.assertEqual(len(errors), 1)
        self.assertIn("pexels", errors[0])

    def test_dedupes_same_ref_across_queries(self):
        p = PexelsProvider("k", opener=lambda url: PEXELS_PHOTO_FIXTURE)
        candidates, _ = search_all([p], ["rain", "window"])
        self.assertEqual(len(candidates), 1)


def cand(**kw):
    base = dict(provider="pexels", provider_ref="1", kind="photo",
                width=3000, height=4500, page_url="", download_url="u",
                license="Pexels License",
                tags="rain window mood", query="rain on window glass")
    base.update(kw)
    return MediaCandidate(**base)


SCENE = {"queries": ["rain on window glass", "person walking rain umbrella"],
         "subjects": ["rain", "window"], "lyric": "rain on the window"}


class TestRanking(unittest.TestCase):
    def test_relevant_portrait_beats_landscape(self):
        portrait = cand()
        landscape = cand(provider_ref="2", width=4500, height=3000)
        ranked, rejected = rank_media([landscape, portrait], SCENE)
        self.assertEqual(rejected, [])
        self.assertEqual(ranked[0].candidate.provider_ref, "1")

    def test_small_photo_rejected_no_enlargement(self):
        small = cand(provider_ref="3", width=800, height=1200)
        ranked, rejected = rank_media([small], SCENE)
        self.assertEqual(ranked, [])
        self.assertIn("enlargement", rejected[0][1])

    def test_watermark_tags_rejected(self):
        marked = cand(provider_ref="4", tags="city skyline watermark")
        _, rejected = rank_media([marked], SCENE)
        self.assertIn("watermark", rejected[0][1])

    def test_low_res_video_rejected(self):
        video = cand(provider_ref="5", kind="video", width=406, height=720,
                     duration=30.0)
        _, rejected = rank_media([video], SCENE)
        self.assertIn("1080", rejected[0][1])

    def test_short_video_rejected_for_long_scene(self):
        video = cand(provider_ref="6", kind="video", width=1080, height=1920,
                     duration=2.0)
        _, rejected = rank_media([video], SCENE, scene_duration=6.0)
        self.assertIn("too short", rejected[0][1])

    def test_relevance_moves_score(self):
        relevant = cand()
        unrelated = cand(provider_ref="7", tags="sports car race",
                         query="sports car")
        s_rel, _ = score_media(relevant, SCENE)
        s_unrel, _ = score_media(unrelated, SCENE)
        self.assertGreater(s_rel, s_unrel)


def make_image(seed=0, size=(200, 300), block=None):
    """Structured synthetic photo: gradient plus seed-placed rectangles.

    (Pure noise defeats perceptual hashing by design — real photos have
    structure, so the fixtures must too.)
    """
    rng = np.random.default_rng(seed)
    w, h = size
    xs = np.linspace(0, 200, w, dtype=np.float32)[None, :, None]
    ys = np.linspace(0, 55, h, dtype=np.float32)[:, None, None]
    arr = np.clip(xs + ys, 0, 255).astype(np.uint8).repeat(3, axis=2)
    for _ in range(5):
        rx, ry = rng.integers(0, w // 2), rng.integers(0, h // 2)
        rw, rh = rng.integers(w // 6, w // 2), rng.integers(h // 6, h // 2)
        arr[ry:ry + rh, rx:rx + rw] = rng.integers(0, 255, size=3)
    if block:
        x, y, bw, bh, value = block
        arr[y:y + bh, x:x + bw] = value
    return Image.fromarray(arr)


class TestDedup(unittest.TestCase):
    def test_identical_and_resized_images_match(self):
        img = make_image(1)
        self.assertEqual(hamming(dhash(img), dhash(img)), 0)
        resized = img.resize((100, 150))
        self.assertLessEqual(hamming(dhash(img), dhash(resized)), 8)

    def test_different_images_do_not_match(self):
        a, b = make_image(1), make_image(2)
        self.assertGreater(hamming(dhash(a), dhash(b)), 8)

    def test_is_duplicate(self):
        h = dhash(make_image(1))
        self.assertTrue(is_duplicate(h, [h]))
        self.assertFalse(is_duplicate(h, [dhash(make_image(2))]))
        self.assertFalse(is_duplicate(h, []))


class TestMediaStoreAndFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = MediaStore(self.dir / "media.db")
        self.job = "a" * 32

    def tearDown(self):
        self.tmp.cleanup()

    def img_bytes(self, seed=1, size=(2000, 3000)):
        from io import BytesIO
        buf = BytesIO()
        make_image(seed, size=size).save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def test_attribution_roundtrip(self):
        self.store.record_asset(self.job, 0, cand(), self.dir / "x.jpg",
                                phash=0xabc, score=0.8)
        [asset] = self.store.list_assets(self.job)
        self.assertEqual(asset["provider"], "pexels")
        self.assertEqual(asset["license"], "Pexels License")
        self.assertEqual(asset["creator"], "")
        self.assertEqual(self.store.existing_hashes(self.job), [0xabc])
        self.assertIn(("pexels", "1"), self.store.used_refs(self.job))

    def test_fetch_photo_verifies_and_hashes(self):
        blob = self.img_bytes()
        path, phash = fetch_photo(cand(width=2000, height=3000), self.dir,
                                  opener=lambda url: blob)
        self.assertTrue(Path(path).exists())
        self.assertIsInstance(phash, int)

    def test_fetch_photo_rejects_undersized_actual_file(self):
        blob = self.img_bytes(size=(400, 600))
        with self.assertRaises(MediaProviderError):
            fetch_photo(cand(), self.dir, opener=lambda url: blob)

    def test_pick_and_fetch_skips_duplicates_and_used(self):
        from media.ranking import RankedMedia
        blob_a = self.img_bytes(seed=1)
        blob_dup = self.img_bytes(seed=1)     # same picture, other provider
        blob_b = self.img_bytes(seed=99)
        blobs = {"ua": blob_a, "udup": blob_dup, "ub": blob_b}
        opener = lambda url: blobs[url]

        ranked0 = [RankedMedia(cand(download_url="ua"), 0.9, [])]
        chosen, _ = pick_and_fetch(ranked0, self.job, 0, self.store,
                                   self.dir, opener=opener)
        self.assertEqual(chosen.provider_ref, "1")

        ranked1 = [
            RankedMedia(cand(download_url="ua"), 0.95, []),                 # used ref
            RankedMedia(cand(provider="pixabay", provider_ref="9",
                             download_url="udup"), 0.9, []),                # duplicate
            RankedMedia(cand(provider="unsplash", provider_ref="z",
                             download_url="ub"), 0.5, []),
        ]
        chosen, _ = pick_and_fetch(ranked1, self.job, 1, self.store,
                                   self.dir, opener=opener)
        self.assertEqual(chosen.provider, "unsplash")
        self.assertEqual(len(self.store.list_assets(self.job)), 2)

    def test_pick_and_fetch_raises_when_nothing_usable(self):
        from media.ranking import RankedMedia
        ranked = [RankedMedia(cand(download_url="ua"), 0.9, [])]
        with self.assertRaises(MediaProviderError):
            pick_and_fetch(ranked, self.job, 0, self.store, self.dir,
                           opener=lambda url: (_ for _ in ()).throw(
                               MediaProviderError("boom")))


class TestCrop(unittest.TestCase):
    def test_adaptation_decisions(self):
        from media.crop import adaptation_plan
        self.assertEqual(adaptation_plan(2000, 3000, "doodleMemory")["strategy"],
                         "portrait_crop")
        self.assertEqual(adaptation_plan(4000, 2200, "doodleMemory")["strategy"],
                         "subject_crop")
        self.assertEqual(adaptation_plan(1920, 1080, "doodleMemory")["strategy"],
                         "blur_fill")
        self.assertEqual(adaptation_plan(4000, 2200, "archiveCollage")["strategy"],
                         "layered_frame")

    def test_subject_crop_rect_valid_and_aspect(self):
        from media.crop import subject_crop
        img = make_image(3, size=(1600, 900),
                         block=(1200, 300, 250, 400, 255))
        x, y, w, h = subject_crop(img)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 1600)
        self.assertLessEqual(y + h, 900)
        self.assertAlmostEqual(w / h, 9 / 16, delta=0.03)

    def test_subject_crop_finds_busy_region(self):
        from media.crop import subject_crop
        # flat gray image with one noisy bright block on the right
        base = Image.new("RGB", (1600, 900), (128, 128, 128))
        noise = make_image(5, size=(300, 500))
        base.paste(noise, (1200, 200))
        x, _, w, _ = subject_crop(base)
        self.assertGreater(x + w / 2, 800, "crop should center on the busy right side")

    def test_deterministic(self):
        from media.crop import subject_crop
        img = make_image(7, size=(1600, 900))
        self.assertEqual(subject_crop(img), subject_crop(img))

class TestArtStyles(unittest.TestCase):
    """Selectable AI art directions for drawn (Doodle) scenes."""

    def _scene(self):
        return {"queries": ["rainy city street"], "emotion": "melancholy",
                "lyric": "walking home alone", "scene_index": 0}

    def test_each_style_produces_distinct_prompt(self):
        from media.genai import ART_STYLES, build_prompt
        seen = {}
        for key in ART_STYLES:
            p = build_prompt(self._scene(), style=key)
            self.assertTrue(p, key)
            self.assertNotIn(p, seen.values(),
                             f"{key} prompt not distinct")
            seen[key] = p

    def test_all_drawn_styles_forbid_text(self):
        from media.genai import ART_STYLES, build_prompt
        for key in ART_STYLES:
            p = build_prompt(self._scene(), style=key)
            self.assertIn("no text", p, key)
            if key != "photo":
                # drawn styles never quote the lyric (avoids garbled text)
                self.assertNotIn("walking home alone", p, key)

    def test_doodle_alias_maps_to_storybook(self):
        from media.genai import build_prompt
        self.assertEqual(build_prompt(self._scene(), style="doodle"),
                         build_prompt(self._scene(), style="storybook"))

    def test_only_storybook_uses_boil(self):
        from media.genai import ART_STYLES, art_style_uses_boil
        self.assertTrue(art_style_uses_boil("storybook"))
        self.assertTrue(art_style_uses_boil("doodle"))
        for key in ("ghibli", "realistic", "watercolor", "anime", "oil"):
            self.assertFalse(art_style_uses_boil(key), key)

    def test_unknown_style_falls_back_to_photo(self):
        from media.genai import build_prompt
        self.assertEqual(build_prompt(self._scene(), style="zzz"),
                         build_prompt(self._scene(), style="photo"))


if __name__ == "__main__":
    unittest.main()
