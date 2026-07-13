"""Unit tests for project history, media exclusion, and safe cleanup."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media.providers import MediaCandidate
from media.store import MediaStore
from projects import PREVIEW_MAX_AGE, ProjectStore, plan_cleanup, run_cleanup

JOB_A, JOB_B = "a" * 32, "b" * 32


class TestProjectStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.tmp.name) / "projects.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_settings_outputs_roundtrip(self):
        self.store.record_ingest(JOB_A, url="https://youtu.be/x" * 1,
                                 video_id="abcdefghijk", title="Song",
                                 uploader="Artist", duration=200.0,
                                 audio_path="/tmp/audio.m4a")
        self.store.update_settings(JOB_A, style="doodleMemory",
                                   target_seconds=45.0, segment_start=60.0)
        self.store.record_output(JOB_A, "/tmp/video.mp4",
                                 style="doodleMemory", duration=45.0)
        # reopen from disk: history must survive a relaunch
        reopened = ProjectStore(self.store.db_path)
        [p] = reopened.list_projects()
        self.assertEqual(p["title"], "Song")
        self.assertEqual(p["style"], "doodleMemory")
        self.assertEqual(p["segment_start"], 60.0)
        self.assertEqual(len(p["outputs"]), 1)
        self.assertEqual(p["outputs"][0]["file_path"], "/tmp/video.mp4")

    def test_reingest_updates_not_duplicates(self):
        self.store.record_ingest(JOB_A, title="One")
        self.store.record_ingest(JOB_A, title="Two")
        projects = self.store.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["title"], "Two")

    def test_output_for_unknown_job_creates_row(self):
        self.store.record_output(JOB_B, "/tmp/v.mp4", style="archiveCollage")
        [p] = self.store.list_projects()
        self.assertEqual(p["job_id"], JOB_B)
        self.assertEqual(len(p["outputs"]), 1)

    def test_delete_project_cascades_outputs(self):
        self.store.record_output(JOB_A, "/tmp/v.mp4")
        self.assertTrue(self.store.delete_project(JOB_A))
        self.assertFalse(self.store.delete_project(JOB_A))
        self.assertEqual(self.store.list_projects(), [])


class TestMediaExclusion(unittest.TestCase):
    def test_exclude_removes_asset_and_blocks_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MediaStore(Path(tmp) / "media.db")
            cand = MediaCandidate(provider="pexels", provider_ref="7",
                                  kind="photo", width=2000, height=3000,
                                  page_url="", download_url="u")
            store.record_asset(JOB_A, 0, cand, "/tmp/x.jpg", phash=0x1)
            store.exclude_asset(JOB_A, "pexels", "7")
            self.assertEqual(store.list_assets(JOB_A), [])
            self.assertIn(("pexels", "7"), store.excluded_refs(JOB_A))
            # exclusion is per-project
            self.assertEqual(store.excluded_refs(JOB_B), set())

    def test_clear_assets_keeps_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MediaStore(Path(tmp) / "media.db")
            store.exclude_asset(JOB_A, "pexels", "9")
            store.clear_assets(JOB_A)
            self.assertIn(("pexels", "9"), store.excluded_refs(JOB_A))


class TestCleanup(unittest.TestCase):
    def test_plan_cleanup_decisions(self):
        now = time.time()
        doomed = plan_cleanup(
            job_dirs=[("/c/jobs/known", "known"), ("/c/jobs/orphan", "orphan"),
                      ("/c/jobs/active", "active")],
            media_dirs=[("/c/media/orphan", "orphan")],
            preview_files=[("/o/prev_old.mp4", now - PREVIEW_MAX_AGE - 10),
                           ("/o/prev_new.mp4", now - 60)],
            known_job_ids={"known"}, active_job_ids={"active"}, now=now)
        self.assertIn("/c/jobs/orphan", doomed)
        self.assertIn("/c/media/orphan", doomed)
        self.assertIn("/o/prev_old.mp4", doomed)
        self.assertNotIn("/c/jobs/known", doomed)
        self.assertNotIn("/c/jobs/active", doomed)
        self.assertNotIn("/o/prev_new.mp4", doomed)

    def test_run_cleanup_never_touches_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProjectStore(root / "Cache" / "projects.db")
            store.record_ingest(JOB_A)
            # known job dir + orphan job dir + orphan media + old preview
            (root / "Cache" / "jobs" / JOB_A).mkdir(parents=True)
            orphan = root / "Cache" / "jobs" / JOB_B
            orphan.mkdir(parents=True)
            (orphan / "audio.m4a").write_bytes(b"x" * 100)
            (root / "Cache" / "media" / JOB_B).mkdir(parents=True)
            previews = root / "Output" / "subtitle_previews"
            previews.mkdir(parents=True)
            old = previews / "old.mp4"
            old.write_bytes(b"y")
            import os
            os.utime(old, (time.time() - PREVIEW_MAX_AGE - 100,) * 2)
            videos = root / "Output" / "videos"
            videos.mkdir(parents=True)
            keep_video = videos / "keep.mp4"
            keep_video.write_bytes(b"z" * 50)

            count, freed = run_cleanup(root, store, active_job_ids=set())
            self.assertGreaterEqual(count, 3)
            self.assertGreater(freed, 0)
            self.assertFalse(orphan.exists())
            self.assertFalse(old.exists())
            self.assertTrue((root / "Cache" / "jobs" / JOB_A).exists())
            self.assertTrue(keep_video.exists(),
                            "rendered outputs must survive cleanup")


if __name__ == "__main__":
    unittest.main()
