"""Lyrics provider adapters (Phase 3).

Providers are replaceable behind one small interface: `search(...)` returns
`LyricsCandidate`s. Network access is LRCLIB only (free, keyless, supports
plain + synchronized lyrics); a local-file provider covers fully-offline use
with user-supplied .lrc/.txt files. Results are cached by the store — we
never build or redistribute a lyrics database.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .models import LyricsCandidate

USER_AGENT = "AutoLyricMac/0.3 (local personal-use app)"


class LyricsProviderError(Exception):
    """Human-readable provider failure (network, bad response, ...)."""


class LRCLIBProvider:
    """lrclib.net adapter — plain and synchronized lyrics, no API key."""

    name = "lrclib"

    def __init__(self, base_url="https://lrclib.net/api", timeout=15, opener=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # injectable for tests: callable(url) -> decoded JSON object
        self._fetch = opener or self._fetch_json

    def _fetch_json(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise LyricsProviderError(f"LRCLIB returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LyricsProviderError(f"Could not reach LRCLIB: {exc}") from exc

    def search(self, artist, title, album="", duration=None):
        """Exact /get lookup first (when duration is known), then /search."""
        results = []
        seen_refs = set()

        if artist and title and duration:
            params = urllib.parse.urlencode({
                "artist_name": artist, "track_name": title,
                "album_name": album or "", "duration": int(round(duration)),
            })
            exact = self._fetch(f"{self.base_url}/get?{params}")
            if isinstance(exact, dict):
                cand = self._to_candidate(exact)
                if cand:
                    results.append(cand)
                    seen_refs.add(cand.provider_ref)

        query = " ".join(p for p in (artist, title) if p).strip()
        if query:
            params = urllib.parse.urlencode({"q": query})
            found = self._fetch(f"{self.base_url}/search?{params}") or []
            if not isinstance(found, list):
                raise LyricsProviderError("LRCLIB search returned an unexpected payload.")
            for item in found[:20]:
                cand = self._to_candidate(item)
                if cand and cand.provider_ref not in seen_refs:
                    results.append(cand)
                    seen_refs.add(cand.provider_ref)
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
