"""Persistent cache for paid API results (Claude, fal.ai).

Every paid call is keyed and stored in Cache/llm_cache.db (JSON values) or
Cache/genai/ (images), so rebuilding a plan, re-aligning, or regenerating
media never pays twice for the same input.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "Cache" / "llm_cache.db"


def _conn():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB)
    c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return c


def key_for(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts)
                          .encode()).hexdigest()


def get_json(key):
    with _conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def put_json(key, value):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?,?)",
                  (key, json.dumps(value)))


GENAI_DIR = _DB.parent / "genai"


def cached_image_path(prompt):
    return GENAI_DIR / f"{key_for('img', prompt)}.jpg"
