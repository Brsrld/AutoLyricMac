"""Project history and safe cache cleanup (Phase 7).

`ProjectStore` persists every ingested source, its latest plan settings and
every rendered output in Cache/projects.db, so relaunching the app restores
history (audio, lyrics, plans and media all live on disk keyed by job id).

`plan_cleanup` is a pure decision function: given what exists and what is
referenced, it returns exactly which paths may be deleted. Rendered videos
in Output/videos are NEVER candidates — active outputs must survive cleanup.
"""

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    job_id       TEXT PRIMARY KEY,
    url          TEXT,
    video_id     TEXT,
    title        TEXT,
    uploader     TEXT,
    duration     REAL,
    audio_path   TEXT,
    style        TEXT,
    target_seconds REAL,
    segment_start  REAL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs (
    id          INTEGER PRIMARY KEY,
    job_id      TEXT NOT NULL REFERENCES projects(job_id) ON DELETE CASCADE,
    file_path   TEXT NOT NULL,
    style       TEXT,
    duration    REAL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS publishes (
    id          INTEGER PRIMARY KEY,
    job_id      TEXT NOT NULL,
    platform    TEXT NOT NULL,
    url         TEXT NOT NULL,
    privacy     TEXT,
    created_at  REAL NOT NULL
);
"""


class ProjectStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        return conn

    def record_ingest(self, job_id, url=None, video_id=None, title=None,
                      uploader=None, duration=None, audio_path=None):
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects (job_id, url, video_id, title, uploader,"
                " duration, audio_path, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(job_id) DO UPDATE SET url=excluded.url,"
                " video_id=excluded.video_id, title=excluded.title,"
                " uploader=excluded.uploader, duration=excluded.duration,"
                " audio_path=excluded.audio_path, updated_at=excluded.updated_at",
                (job_id, url, video_id, title, uploader, duration,
                 audio_path, now, now))

    def _ensure_row(self, conn, job_id):
        conn.execute(
            "INSERT OR IGNORE INTO projects (job_id, created_at, updated_at)"
            " VALUES (?,?,?)", (job_id, time.time(), time.time()))

    def update_settings(self, job_id, style=None, target_seconds=None,
                        segment_start=None):
        sets, args = ["updated_at=?"], [time.time()]
        for column, value in (("style", style),
                              ("target_seconds", target_seconds),
                              ("segment_start", segment_start)):
            if value is not None:
                sets.append(f"{column}=?")
                args.append(value)
        with self._connect() as conn:
            self._ensure_row(conn, job_id)
            conn.execute(f"UPDATE projects SET {', '.join(sets)}"
                         " WHERE job_id=?", (*args, job_id))

    def record_output(self, job_id, file_path, style=None, duration=None):
        with self._connect() as conn:
            self._ensure_row(conn, job_id)
            conn.execute(
                "INSERT INTO outputs (job_id, file_path, style, duration,"
                " created_at) VALUES (?,?,?,?,?)",
                (job_id, str(file_path), style, duration, time.time()))
            conn.execute("UPDATE projects SET updated_at=? WHERE job_id=?",
                         (time.time(), job_id))

    def record_publish(self, job_id, platform, url, privacy=None):
        with self._connect() as conn:
            self._ensure_row(conn, job_id)
            conn.execute(
                "INSERT INTO publishes (job_id, platform, url, privacy,"
                " created_at) VALUES (?,?,?,?,?)",
                (job_id, platform, url, privacy, time.time()))

    def list_projects(self):
        with self._connect() as conn:
            projects = [dict(r) for r in conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC")]
            for p in projects:
                p["outputs"] = [dict(r) for r in conn.execute(
                    "SELECT file_path, style, duration, created_at FROM outputs"
                    " WHERE job_id=? ORDER BY created_at DESC",
                    (p["job_id"],))]
                p["publishes"] = [dict(r) for r in conn.execute(
                    "SELECT platform, url, privacy, created_at FROM publishes"
                    " WHERE job_id=? ORDER BY created_at DESC",
                    (p["job_id"],))]
        return projects

    def get_project(self, job_id):
        for p in self.list_projects():
            if p["job_id"] == job_id:
                return p
        return None

    def delete_project(self, job_id):
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE job_id=?",
                               (job_id,))
            return cur.rowcount > 0

    def known_job_ids(self):
        with self._connect() as conn:
            return {r["job_id"] for r in
                    conn.execute("SELECT job_id FROM projects")}


# ---------------------------------------------------------------------------
# Safe cleanup (pure decision + thin executor)
# ---------------------------------------------------------------------------

PREVIEW_MAX_AGE = 7 * 24 * 3600


def plan_cleanup(job_dirs, media_dirs, preview_files, known_job_ids,
                 active_job_ids, now):
    """Decide what may be deleted. Pure.

    - Cache/jobs/<id> and Cache/media/<id> whose id is neither in history
      nor currently running are orphans -> delete.
    - Subtitle previews (mp4/png) older than PREVIEW_MAX_AGE -> delete.
    - Anything else — notably Output/videos — is never listed.

    Inputs are (path, job_id) pairs / (path, mtime) pairs so the decision
    needs no filesystem access.
    """
    keep = set(known_job_ids) | set(active_job_ids)
    doomed = [path for path, job_id in job_dirs if job_id not in keep]
    doomed += [path for path, job_id in media_dirs if job_id not in keep]
    doomed += [path for path, mtime in preview_files
               if now - mtime > PREVIEW_MAX_AGE]
    return doomed


def run_cleanup(repo_root, store, active_job_ids):
    """Execute plan_cleanup against the real cache; returns (count, bytes)."""
    import shutil

    repo_root = Path(repo_root)
    now = time.time()

    def dirs_with_ids(base):
        if not base.is_dir():
            return []
        return [(p, p.name) for p in base.iterdir() if p.is_dir()]

    previews = []
    preview_dir = repo_root / "Output" / "subtitle_previews"
    if preview_dir.is_dir():
        previews = [(p, p.stat().st_mtime) for p in preview_dir.iterdir()
                    if p.is_file()]

    doomed = plan_cleanup(dirs_with_ids(repo_root / "Cache" / "jobs"),
                          dirs_with_ids(repo_root / "Cache" / "media"),
                          previews, store.known_job_ids(), active_job_ids,
                          now)
    freed = 0
    for path in doomed:
        path = Path(path)
        try:
            if path.is_dir():
                freed += sum(f.stat().st_size for f in path.rglob("*")
                             if f.is_file())
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
        except OSError:
            continue
    return len(doomed), freed
