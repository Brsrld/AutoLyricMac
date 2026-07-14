"""Canonical lyrics storage (SQLite, Phase 3).

One row of `lyrics` per ingestion job, with `lines` and `words` carrying
timing + confidence from alignment, user corrections and translations that
persist across sessions, and a small provider response cache so repeated
searches stay off the network. Confidence semantics: NULL = never aligned,
0..1 = alignment confidence; anything below `UNCERTAIN_BELOW` must be
surfaced as uncertain, never displayed silently.
"""

import json
import sqlite3
import time
from pathlib import Path

from .lrc import infer_line_ends, parse_lrc, plain_lines
from .models import LyricsCandidate

UNCERTAIN_BELOW = 0.55       # per-line confidence below this is flagged
SUSPECT_BELOW = 0.35         # whole-lyrics mean below this = likely wrong song
CACHE_TTL_SECONDS = 7 * 24 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lyrics (
    id            INTEGER PRIMARY KEY,
    job_id        TEXT NOT NULL UNIQUE,
    provider      TEXT NOT NULL,
    provider_ref  TEXT,
    artist        TEXT,
    title         TEXT,
    album         TEXT,
    duration      REAL,
    synced        INTEGER NOT NULL DEFAULT 0,
    raw_text      TEXT NOT NULL,
    raw_lrc       TEXT,
    score         REAL,
    matched_ratio REAL,
    mean_confidence REAL,
    fetched_at    REAL NOT NULL,
    aligned_at    REAL
);
CREATE TABLE IF NOT EXISTS lines (
    id          INTEGER PRIMARY KEY,
    lyrics_id   INTEGER NOT NULL REFERENCES lyrics(id) ON DELETE CASCADE,
    line_index  INTEGER NOT NULL,
    text        TEXT NOT NULL,
    corrected_text TEXT,
    translation TEXT,
    start       REAL,
    end         REAL,
    confidence  REAL,
    UNIQUE(lyrics_id, line_index)
);
CREATE TABLE IF NOT EXISTS words (
    id          INTEGER PRIMARY KEY,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    word_index  INTEGER NOT NULL,
    text        TEXT NOT NULL,
    start       REAL,
    end         REAL,
    confidence  REAL,
    UNIQUE(line_id, word_index)
);
CREATE TABLE IF NOT EXISTS provider_cache (
    cache_key   TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    fetched_at  REAL NOT NULL
);
"""


class LyricsStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        return conn

    # ------------------------------------------------------------------
    # Saving canonical lyrics
    # ------------------------------------------------------------------

    def save_lyrics(self, job_id, candidate, score=None, track_duration=None):
        """Persist a chosen candidate as this job's canonical lyrics.

        Replaces any previous lyrics for the job (corrections belong to a
        lyrics choice, so they are replaced too — the UI warns before
        re-fetching). Synced candidates seed line timings from their LRC tags.
        """
        if candidate.synced:
            _, lrc_lines = parse_lrc(candidate.lrc_text)
            texts = [l.text for l in lrc_lines if l.text]
            lrc_lines = [l for l in lrc_lines if l.text]
            spans = infer_line_ends(lrc_lines, track_duration)
        else:
            texts = plain_lines(candidate.plain_text)
            lrc_lines, spans = None, None

        with self._connect() as conn:
            conn.execute("DELETE FROM lyrics WHERE job_id = ?", (job_id,))
            cur = conn.execute(
                "INSERT INTO lyrics (job_id, provider, provider_ref, artist, title,"
                " album, duration, synced, raw_text, raw_lrc, score, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, candidate.provider, candidate.provider_ref,
                 candidate.artist, candidate.title, candidate.album,
                 candidate.duration, int(candidate.synced),
                 candidate.plain_text or "\n".join(texts),
                 candidate.lrc_text or None, score, time.time()))
            lyrics_id = cur.lastrowid
            for i, text in enumerate(texts):
                start = end = None
                if spans is not None:
                    start, end = spans[i]
                cur = conn.execute(
                    "INSERT INTO lines (lyrics_id, line_index, text, start, end)"
                    " VALUES (?,?,?,?,?)", (lyrics_id, i, text, start, end))
                line_id = cur.lastrowid
                if lrc_lines is not None and lrc_lines[i].words:
                    for wi, w in enumerate(lrc_lines[i].words):
                        conn.execute(
                            "INSERT INTO words (line_id, word_index, text, start)"
                            " VALUES (?,?,?,?)", (line_id, wi, w.text, w.start))
        return lyrics_id

    # ------------------------------------------------------------------
    # Alignment results
    # ------------------------------------------------------------------

    def apply_alignment(self, job_id, aligned_lines, matched_ratio, mean_confidence):
        """Store per-line/word timing + confidence from the aligner.

        `aligned_lines` is a list of dicts: {line_index, start, end,
        confidence, words: [{text, start, end, confidence}]}.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM lyrics WHERE job_id = ?",
                               (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"no lyrics stored for job {job_id}")
            lyrics_id = row["id"]
            for al in aligned_lines:
                cur = conn.execute(
                    "UPDATE lines SET start=?, end=?, confidence=?"
                    " WHERE lyrics_id=? AND line_index=?",
                    (al.get("start"), al.get("end"), al.get("confidence"),
                     lyrics_id, al["line_index"]))
                if cur.rowcount == 0:
                    continue
                line_id = conn.execute(
                    "SELECT id FROM lines WHERE lyrics_id=? AND line_index=?",
                    (lyrics_id, al["line_index"])).fetchone()["id"]
                conn.execute("DELETE FROM words WHERE line_id=?", (line_id,))
                for wi, w in enumerate(al.get("words", [])):
                    conn.execute(
                        "INSERT INTO words (line_id, word_index, text, start, end,"
                        " confidence) VALUES (?,?,?,?,?,?)",
                        (line_id, wi, w["text"], w.get("start"), w.get("end"),
                         w.get("confidence")))
            conn.execute(
                "UPDATE lyrics SET matched_ratio=?, mean_confidence=?, aligned_at=?"
                " WHERE id=?",
                (matched_ratio, mean_confidence, time.time(), lyrics_id))

    # ------------------------------------------------------------------
    # Corrections / translations (persist across sessions)
    # ------------------------------------------------------------------

    def update_line(self, job_id, line_index, corrected_text=..., translation=...):
        """Update a line's user correction and/or translation.

        Pass an explicit empty string to clear a correction (reverts to the
        canonical text) or a translation. `...` means "leave unchanged".
        """
        sets, args = [], []
        if corrected_text is not ...:
            value = (corrected_text or "").strip()
            sets.append("corrected_text=?")
            args.append(value if value and value != "" else None)
        if translation is not ...:
            value = (translation or "").strip()
            sets.append("translation=?")
            args.append(value or None)
        if not sets:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE lines SET {', '.join(sets)}"
                " WHERE line_index=? AND lyrics_id="
                " (SELECT id FROM lyrics WHERE job_id=?)",
                (*args, line_index, job_id))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_lyrics(self, job_id):
        """Full payload for the app: lines, words, confidence, uncertainty."""
        with self._connect() as conn:
            lyr = conn.execute("SELECT * FROM lyrics WHERE job_id=?",
                               (job_id,)).fetchone()
            if lyr is None:
                return None
            lines = []
            for row in conn.execute(
                    "SELECT * FROM lines WHERE lyrics_id=? ORDER BY line_index",
                    (lyr["id"],)):
                words = [
                    {"text": w["text"], "start": w["start"], "end": w["end"],
                     "confidence": w["confidence"]}
                    for w in conn.execute(
                        "SELECT * FROM words WHERE line_id=? ORDER BY word_index",
                        (row["id"],))]
                conf = row["confidence"]
                display = row["corrected_text"] if row["corrected_text"] is not None \
                    else row["text"]
                lines.append({
                    "line_index": row["line_index"],
                    "text": row["text"],
                    "corrected_text": row["corrected_text"],
                    "display_text": display,
                    "translation": row["translation"],
                    "start": row["start"],
                    "end": row["end"],
                    "confidence": conf,
                    "uncertain": conf is not None and conf < UNCERTAIN_BELOW,
                    "words": words,
                })
            # immutable synced-LRC spans, re-parsed from the raw LRC so they
            # survive alignment (which overwrites lines.start/end). Keyed by
            # line_index, exactly matching how save_lyrics assigned them.
            lrc_spans = {}
            if lyr["synced"] and lyr["raw_lrc"]:
                try:
                    _, lrc_lines = parse_lrc(lyr["raw_lrc"])
                    lrc_lines = [l for l in lrc_lines if l.text]
                    spans = infer_line_ends(lrc_lines, lyr["duration"])
                    lrc_spans = {i: (sp[0], sp[1]) for i, sp in enumerate(spans)}
                except Exception:
                    lrc_spans = {}
            mean_conf = lyr["mean_confidence"]
            return {
                "job_id": job_id,
                "provider": lyr["provider"],
                "artist": lyr["artist"],
                "title": lyr["title"],
                "album": lyr["album"],
                "synced": bool(lyr["synced"]),
                "score": lyr["score"],
                "aligned": lyr["aligned_at"] is not None,
                "matched_ratio": lyr["matched_ratio"],
                "mean_confidence": mean_conf,
                "suspect": mean_conf is not None and mean_conf < SUSPECT_BELOW,
                "lines": lines,
                "lrc_spans": lrc_spans,
            }

    # ------------------------------------------------------------------
    # Provider response cache
    # ------------------------------------------------------------------

    def cached_search(self, cache_key, ttl=CACHE_TTL_SECONDS):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at FROM provider_cache WHERE cache_key=?",
                (cache_key,)).fetchone()
        if row is None or time.time() - row["fetched_at"] > ttl:
            return None
        return [LyricsCandidate(**item) for item in json.loads(row["payload"])]

    def store_search(self, cache_key, candidates):
        payload = json.dumps([c.__dict__ for c in candidates])
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO provider_cache (cache_key, payload,"
                " fetched_at) VALUES (?,?,?)", (cache_key, payload, time.time()))
