"""Media asset store: downloads, perceptual dedup, attribution history.

Every used asset is recorded with provider/creator/source/license so
attribution history survives (Phase 4 requirement). Files live under
Cache/media/<job_id>/; the SQLite DB lives next to the lyrics DB.
"""

import sqlite3
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from .dedup import dhash, is_duplicate
from .providers import USER_AGENT, MediaProviderError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS excluded (
    job_id       TEXT NOT NULL,
    provider     TEXT NOT NULL,
    provider_ref TEXT NOT NULL,
    PRIMARY KEY (job_id, provider, provider_ref)
);
CREATE TABLE IF NOT EXISTS assets (
    id           INTEGER PRIMARY KEY,
    job_id       TEXT NOT NULL,
    scene_index  INTEGER NOT NULL,
    provider     TEXT NOT NULL,
    provider_ref TEXT NOT NULL,
    kind         TEXT NOT NULL,
    width        INTEGER,
    height       INTEGER,
    page_url     TEXT,
    creator      TEXT,
    creator_url  TEXT,
    license      TEXT,
    query        TEXT,
    file_path    TEXT NOT NULL,
    phash        TEXT,
    score        REAL,
    fetched_at   REAL NOT NULL,
    UNIQUE(job_id, scene_index)
);
"""

MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024


class MediaStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def record_asset(self, job_id, scene_index, cand, file_path, phash=None,
                     score=None):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO assets (job_id, scene_index, provider,"
                " provider_ref, kind, width, height, page_url, creator,"
                " creator_url, license, query, file_path, phash, score,"
                " fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, scene_index, cand.provider, cand.provider_ref,
                 cand.kind, cand.width, cand.height, cand.page_url,
                 cand.creator, cand.creator_url, cand.license, cand.query,
                 str(file_path), None if phash is None else format(phash, "x"),
                 score, time.time()))

    def list_assets(self, job_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assets WHERE job_id=? ORDER BY scene_index",
                (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def existing_hashes(self, job_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT phash FROM assets WHERE job_id=? AND phash IS NOT NULL",
                (job_id,)).fetchall()
        return [int(r["phash"], 16) for r in rows]

    def used_refs(self, job_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT provider, provider_ref FROM assets WHERE job_id=?",
                (job_id,)).fetchall()
        return {(r["provider"], r["provider_ref"]) for r in rows}

    def exclude_asset(self, job_id, provider, provider_ref):
        """Never offer this asset for this project again (Phase 7)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO excluded (job_id, provider,"
                " provider_ref) VALUES (?,?,?)",
                (job_id, provider, provider_ref))
            conn.execute(
                "DELETE FROM assets WHERE job_id=? AND provider=?"
                " AND provider_ref=?", (job_id, provider, provider_ref))

    def excluded_refs(self, job_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT provider, provider_ref FROM excluded WHERE job_id=?",
                (job_id,)).fetchall()
        return {(r["provider"], r["provider_ref"]) for r in rows}

    def clear_assets(self, job_id):
        """Forget chosen assets (regenerate-media keeps exclusions)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM assets WHERE job_id=?", (job_id,))


def download_bytes(url, timeout=60, opener=None):
    """Fetch a media file with a size cap; returns bytes."""
    if opener is not None:
        return opener(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    except Exception as exc:
        raise MediaProviderError(f"Download failed: {exc}") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise MediaProviderError("File exceeds the 80 MB download cap.")
    return data


def fetch_photo(cand, dest_dir, min_size=(1080, 1600), opener=None):
    """Download + verify a photo. Returns (path, phash).

    Verifies the file actually decodes and meets the candidate's claimed
    size (providers occasionally lie); computes the perceptual hash for
    dedup. Raises MediaProviderError on any problem.
    """
    from PIL import Image

    data = download_bytes(cand.download_url, opener=opener)
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise MediaProviderError(f"Not a decodable image: {exc}") from exc
    w, h = img.size
    if h > w:
        if w < min_size[0] or h < min_size[1]:
            raise MediaProviderError(f"Image smaller than advertised ({w}x{h}).")
    elif min(w, h) < 1400:
        raise MediaProviderError(f"Landscape image too small ({w}x{h}).")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".png" if (img.format or "").upper() == "PNG" else ".jpg"
    path = dest_dir / f"{cand.provider}_{cand.provider_ref}{suffix}"
    path.write_bytes(data)
    return path, dhash(img)


def pick_and_fetch(ranked, job_id, scene_index, store, dest_dir,
                   dedup_threshold=8, opener=None, log=None,
                   avoid_refs=frozenset()):
    """Walk ranked candidates; skip duplicates/repeat refs/bad downloads.

    `avoid_refs` adds extra (provider, ref) pairs to skip this round (used
    by regenerate so replaced assets cannot re-enter via another scene).
    Returns (candidate, path) of the first usable asset and records it with
    attribution, or raises MediaProviderError when everything failed.
    """
    hashes = store.existing_hashes(job_id)
    used = store.used_refs(job_id) | set(avoid_refs)
    excluded = store.excluded_refs(job_id)
    failures = []
    for ranked_item in ranked:
        cand = ranked_item.candidate
        key = (cand.provider, cand.provider_ref)
        if key in excluded:
            failures.append(f"{cand.provider}:{cand.provider_ref} excluded by user")
            continue
        if key in used:
            failures.append(f"{cand.provider}:{cand.provider_ref} already used")
            continue
        if cand.kind != "photo":
            failures.append(f"{cand.provider}:{cand.provider_ref} video fetch "
                            "arrives with the renderer phase")
            continue
        try:
            path, phash = fetch_photo(cand, dest_dir, opener=opener)
        except MediaProviderError as exc:
            failures.append(f"{cand.provider}:{cand.provider_ref} {exc}")
            continue
        if is_duplicate(phash, hashes, dedup_threshold):
            Path(path).unlink(missing_ok=True)
            failures.append(f"{cand.provider}:{cand.provider_ref} perceptual duplicate")
            continue
        store.record_asset(job_id, scene_index, cand, path, phash,
                           ranked_item.score)
        if log:
            log(f"scene {scene_index}: {cand.provider}/{cand.provider_ref} "
                f"score {ranked_item.score:.2f}")
        return cand, path
    raise MediaProviderError(
        "No usable media for this scene: " + "; ".join(failures[:4]))
