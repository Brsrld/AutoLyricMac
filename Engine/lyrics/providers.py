"""Lyrics provider adapters (Phase 3).

Providers are replaceable behind one small interface: `search(...)` returns
`LyricsCandidate`s. Network access is LRCLIB only (free, keyless, supports
plain + synchronized lyrics); a local-file provider covers fully-offline use
with user-supplied .lrc/.txt files. Results are cached by the store — we
never build or redistribute a lyrics database.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .models import LyricsCandidate

USER_AGENT = "AutoLyricMac/0.3 (local personal-use app)"

# YouTube-title noise that ruins an exact lyrics lookup
_TITLE_JUNK = re.compile(r"""(?ix)
    \b(
        official\s*(music\s*)?(video|audio|lyric[s]?\s*video|visualizer|version)
        | lyric[s]?(\s*video)? | audio | video | visualizer
        | hd | 4k | hq | m/?v | mv
        | remaster(ed)?(\s*\d{4})? | remix | live | acoustic | cover | karaoke
        | clip\s*officiel | full\s*(song|album|video) | with\s*lyrics
        | color\s*coded | sub(title)?s?
    )\b""")


def clean_track_name(text):
    """Strip YouTube-title noise (brackets, 'Official Video', feat., | channel)."""
    t = text or ""
    t = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", t)      # (…) […] {…}
    t = re.split(r"\s+[|•·]\s+", t)[0]                       # drop "| channel"
    t = re.sub(r"(?i)\s*(feat\.?|ft\.?|featuring)\s+.*$", "", t)
    t = _TITLE_JUNK.sub(" ", t)
    t = t.replace("“", "").replace("”", "").replace('"', "")
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—•·:|")
    return t


def split_artist_title(raw):
    """Best-effort ('artist', 'title') from an 'Artist - Title' string."""
    for sep in (" - ", " – ", " — ", " · "):
        if sep in (raw or ""):
            a, b = raw.split(sep, 1)
            return a.strip(), b.strip()
    return "", (raw or "").strip()


class LyricsProviderError(Exception):
    """Human-readable provider failure (network, bad response, ...)."""


class LRCLIBProvider:
    """lrclib.net adapter — plain and synchronized lyrics, no API key."""

    name = "lrclib"

    def __init__(self, base_url="https://lrclib.net/api", timeout=15,
                 opener=None, retries=3, sleeper=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.sleeper = sleeper
        # injectable for tests: callable(url) -> decoded JSON object
        self._fetch = opener or self._fetch_json

    def _fetch_json(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                # 429/5xx are transient (LRCLIB overloaded) — back off & retry
                if exc.code in (429, 500, 502, 503, 504) \
                        and attempt < self.retries - 1:
                    self.sleeper(1.5 * (attempt + 1))
                    last = exc
                    continue
                raise LyricsProviderError(
                    f"LRCLIB returned HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError,
                    json.JSONDecodeError) as exc:
                if attempt < self.retries - 1:
                    self.sleeper(1.5 * (attempt + 1))
                    last = exc
                    continue
                raise LyricsProviderError(
                    f"Could not reach LRCLIB: {exc}") from exc
        raise LyricsProviderError(f"Could not reach LRCLIB: {last}")

    def search(self, artist, title, album="", duration=None):
        """Exact /get first, then several cleaned /search queries.

        YouTube titles are noisy ('… (Official Video) [4K]'), which breaks
        LRCLIB's exact match, so we also try a cleaned artist/title, a
        title-only query, and — when no artist was given — an artist parsed
        from an 'Artist - Title' string. Candidates from every query are
        gathered and de-duplicated; ranking picks the best.
        """
        results = []
        seen_refs = set()
        ca, ct = clean_track_name(artist), clean_track_name(title)
        if not ca:                       # no artist? try "Artist - Title"
            pa, pt = split_artist_title(title)
            if pa and pt:
                ca, ct = clean_track_name(pa), clean_track_name(pt)

        def add(item):
            cand = self._to_candidate(item)
            if cand and cand.provider_ref not in seen_refs:
                results.append(cand)
                seen_refs.add(cand.provider_ref)

        # exact lookups (cleaned first, then raw) when duration is known
        for a, t in [(ca, ct), (artist, title)]:
            if a and t and duration:
                params = urllib.parse.urlencode({
                    "artist_name": a, "track_name": t,
                    "album_name": album or "", "duration": int(round(duration))})
                exact = self._fetch(f"{self.base_url}/get?{params}")
                if isinstance(exact, dict):
                    add(exact)
                    break

        # fuzzy searches: cleaned "artist title", cleaned title, raw combo
        queries = []
        for q in (f"{ca} {ct}".strip(), ct,
                  " ".join(p for p in (artist, title) if p).strip()):
            q = q.strip()
            if q and q.lower() not in {x.lower() for x in queries}:
                queries.append(q)
        for q in queries:
            found = self._fetch(
                f"{self.base_url}/search?{urllib.parse.urlencode({'q': q})}") or []
            if not isinstance(found, list):
                continue
            for item in found[:20]:
                add(item)
            if len(results) >= 25:
                break
        return results

    def _to_candidate(self, item):
        if not isinstance(item, dict):
            return None
        plain = item.get("plainLyrics") or ""
        lrc = item.get("syncedLyrics") or ""
        instrumental = bool(item.get("instrumental"))
        if not plain and not lrc and not instrumental:
            return None
        return LyricsCandidate(
            provider=self.name,
            provider_ref=str(item.get("id", "")),
            artist=item.get("artistName") or "",
            title=item.get("trackName") or "",
            album=item.get("albumName") or "",
            duration=item.get("duration"),
            plain_text=plain,
            lrc_text=lrc,
            instrumental=instrumental,
        )


class LocalFileProvider:
    """User-supplied lyrics files: `<anything>.lrc` or `<anything>.txt`.

    Looks in a directory (default `Cache/lyrics_local/`) and in the job's own
    cache directory. File stem is treated as "Artist - Title" when it contains
    " - ", else as the title.
    """

    name = "local_file"

    def __init__(self, directories):
        self.directories = [Path(d) for d in directories]

    def search(self, artist, title, album="", duration=None):
        results = []
        for directory in self.directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() not in (".lrc", ".txt") or not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                stem = path.stem
                file_artist, _, file_title = stem.partition(" - ")
                if not file_title:
                    file_artist, file_title = "", stem
                is_lrc = path.suffix.lower() == ".lrc" or "[00:" in text[:2000]
                results.append(LyricsCandidate(
                    provider=self.name,
                    provider_ref=str(path),
                    artist=file_artist.strip(),
                    title=file_title.strip(),
                    plain_text="" if is_lrc else text,
                    lrc_text=text if is_lrc else "",
                ))
        return results


def default_providers(repo_root, job_dir=None):
    """Provider chain: user files first (explicit intent), then LRCLIB."""
    dirs = [Path(repo_root) / "Cache" / "lyrics_local"]
    if job_dir:
        dirs.insert(0, Path(job_dir))
    return [LocalFileProvider(dirs), LRCLIBProvider()]
