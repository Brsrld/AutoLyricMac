"""Licensed stock-media provider adapters (Phase 4).

One protocol, three adapters: Pexels (primary, photos + videos), Pixabay
(secondary, photos + videos), Unsplash (optional, photos only). API keys are
passed per call and never persisted by the engine — the app keeps them in the
macOS Keychain. Only these official APIs are used; never arbitrary scraping.

`search_all` implements the fallback chain: a failing provider is skipped
(with its error recorded) instead of failing the whole job.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "AutoLyricMac/0.4 (local personal-use app)"


class MediaProviderError(Exception):
    """Provider failure: bad key, quota, network, malformed response."""


@dataclass
class MediaCandidate:
    provider: str
    provider_ref: str
    kind: str                    # "photo" | "video"
    width: int
    height: int
    page_url: str                # human page, for attribution
    download_url: str            # direct file URL (largest reasonable)
    thumb_url: str = ""
    creator: str = ""
    creator_url: str = ""
    license: str = ""
    query: str = ""
    tags: str = ""               # alt text / tags for relevance scoring
    duration: float | None = None

    @property
    def portrait(self):
        return self.height > self.width

    def summary(self):
        return {
            "provider": self.provider, "provider_ref": self.provider_ref,
            "kind": self.kind, "width": self.width, "height": self.height,
            "page_url": self.page_url, "creator": self.creator,
            "license": self.license, "query": self.query,
        }


def _fetch_json(url, headers, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise MediaProviderError("API key rejected (check the key).") from exc
        if exc.code == 429:
            raise MediaProviderError("Rate limit reached; try later.") from exc
        raise MediaProviderError(f"Provider returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MediaProviderError(f"Could not reach provider: {exc}") from exc


class PexelsProvider:
    """api.pexels.com — photos and videos, 'Pexels License'."""

    name = "pexels"
    supports = ("photo", "video")

    def __init__(self, api_key, timeout=20, opener=None):
        self.api_key = api_key
        self.timeout = timeout
        self._fetch = opener or (lambda url: _fetch_json(
            url, {"Authorization": self.api_key}, self.timeout))

    def search(self, query, kind="photo", per_page=12):
        if kind == "video":
            url = ("https://api.pexels.com/videos/search?"
                   + urllib.parse.urlencode({"query": query,
                                             "orientation": "portrait",
                                             "per_page": per_page}))
            data = self._fetch(url)
            return [c for c in (self._video(v, query)
                                for v in data.get("videos", [])) if c]
        url = ("https://api.pexels.com/v1/search?"
               + urllib.parse.urlencode({"query": query,
                                         "orientation": "portrait",
                                         "size": "large",
                                         "per_page": per_page}))
        data = self._fetch(url)
        return [c for c in (self._photo(p, query)
                            for p in data.get("photos", [])) if c]

    def _photo(self, p, query):
        src = p.get("src") or {}
        download = src.get("original") or src.get("large2x")
        if not download:
            return None
        return MediaCandidate(
            provider=self.name, provider_ref=str(p.get("id", "")),
            kind="photo", width=int(p.get("width", 0)),
            height=int(p.get("height", 0)), page_url=p.get("url", ""),
            download_url=download, thumb_url=src.get("medium", ""),
            creator=p.get("photographer", ""),
            creator_url=p.get("photographer_url", ""),
            license="Pexels License", query=query,
            tags=p.get("alt") or "")

    def _video(self, v, query):
        files = sorted((f for f in v.get("video_files", [])
                        if f.get("link") and f.get("height")),
                       key=lambda f: f["height"], reverse=True)
        best = next((f for f in files if f["height"] >= 1080), None) or \
            (files[0] if files else None)
        if best is None:
            return None
        user = v.get("user") or {}
        return MediaCandidate(
            provider=self.name, provider_ref=str(v.get("id", "")),
            kind="video", width=int(best.get("width", 0)),
            height=int(best.get("height", 0)), page_url=v.get("url", ""),
            download_url=best["link"], thumb_url=v.get("image", ""),
            creator=user.get("name", ""), creator_url=user.get("url", ""),
            license="Pexels License", query=query,
            duration=float(v.get("duration", 0)) or None)


class PixabayProvider:
    """pixabay.com/api — photos and videos, 'Pixabay Content License'."""

    name = "pixabay"
    supports = ("photo", "video")

    def __init__(self, api_key, timeout=20, opener=None):
        self.api_key = api_key
        self.timeout = timeout
        self._fetch = opener or (lambda url: _fetch_json(url, {}, self.timeout))

    def search(self, query, kind="photo", per_page=12):
        if kind == "video":
            url = ("https://pixabay.com/api/videos/?"
                   + urllib.parse.urlencode({"key": self.api_key, "q": query,
                                             "per_page": per_page,
                                             "safesearch": "true"}))
            data = self._fetch(url)
            return [c for c in (self._video(h, query)
                                for h in data.get("hits", [])) if c]
        url = ("https://pixabay.com/api/?"
               + urllib.parse.urlencode({"key": self.api_key, "q": query,
                                         "image_type": "photo",
                                         "orientation": "vertical",
                                         "min_width": 1080,
                                         "min_height": 1600,
                                         "per_page": per_page,
                                         "safesearch": "true"}))
        data = self._fetch(url)
        return [c for c in (self._photo(h, query)
                            for h in data.get("hits", [])) if c]

    def _photo(self, h, query):
        download = h.get("largeImageURL") or h.get("fullHDURL")
        if not download:
            return None
        return MediaCandidate(
            provider=self.name, provider_ref=str(h.get("id", "")),
            kind="photo", width=int(h.get("imageWidth", 0)),
            height=int(h.get("imageHeight", 0)),
            page_url=h.get("pageURL", ""), download_url=download,
            thumb_url=h.get("previewURL", ""), creator=h.get("user", ""),
            creator_url=f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/",
            license="Pixabay Content License", query=query,
            tags=h.get("tags", ""))

    def _video(self, h, query):
        videos = h.get("videos") or {}
        best = None
        for variant in ("large", "medium"):
            v = videos.get(variant) or {}
            if v.get("url") and v.get("height", 0) >= 1080:
                best = v
                break
        if best is None:
            v = videos.get("medium") or videos.get("small") or {}
            best = v if v.get("url") else None
        if best is None:
            return None
        return MediaCandidate(
            provider=self.name, provider_ref=str(h.get("id", "")),
            kind="video", width=int(best.get("width", 0)),
            height=int(best.get("height", 0)),
            page_url=h.get("pageURL", ""), download_url=best["url"],
            creator=h.get("user", ""),
            license="Pixabay Content License", query=query,
            tags=h.get("tags", ""),
            duration=float(h.get("duration", 0)) or None)


class UnsplashProvider:
    """api.unsplash.com — photos only, 'Unsplash License'."""

    name = "unsplash"
    supports = ("photo",)

    def __init__(self, api_key, timeout=20, opener=None):
        self.api_key = api_key
        self.timeout = timeout
        self._fetch = opener or (lambda url: _fetch_json(
            url, {"Authorization": f"Client-ID {self.api_key}"}, self.timeout))

    def search(self, query, kind="photo", per_page=12):
        if kind != "photo":
            return []
        url = ("https://api.unsplash.com/search/photos?"
               + urllib.parse.urlencode({"query": query,
                                         "orientation": "portrait",
                                         "per_page": per_page}))
        data = self._fetch(url)
        return [c for c in (self._photo(p, query)
                            for p in data.get("results", [])) if c]

    def _photo(self, p, query):
        urls = p.get("urls") or {}
        download = urls.get("raw") or urls.get("full")
        if not download:
            return None
        user = p.get("user") or {}
        return MediaCandidate(
            provider=self.name, provider_ref=str(p.get("id", "")),
            kind="photo", width=int(p.get("width", 0)),
            height=int(p.get("height", 0)),
            page_url=(p.get("links") or {}).get("html", ""),
            download_url=download, thumb_url=urls.get("small", ""),
            creator=user.get("name", ""),
            creator_url=(user.get("links") or {}).get("html", ""),
            license="Unsplash License", query=query,
            tags=" ".join(filter(None, [p.get("alt_description"),
                                        p.get("description")])))


def build_providers(keys):
    """Provider chain from available keys, in preference order."""
    chain = []
    if keys.get("pexels"):
        chain.append(PexelsProvider(keys["pexels"]))
    if keys.get("pixabay"):
        chain.append(PixabayProvider(keys["pixabay"]))
    if keys.get("unsplash"):
        chain.append(UnsplashProvider(keys["unsplash"]))
    return chain


def search_all(providers, queries, kind="photo", per_query=8):
    """Query every provider; a failing provider is skipped, not fatal.

    Returns (candidates, errors) — errors is a list of human-readable
    strings, one per provider failure.
    """
    candidates, errors = [], []
    seen = set()
    for provider in providers:
        if kind not in provider.supports:
            continue
        for query in queries:
            try:
                found = provider.search(query, kind=kind, per_page=per_query)
            except MediaProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                break  # this provider is unhealthy; move to the next one
            for cand in found:
                key = (cand.provider, cand.provider_ref)
                if key not in seen:
                    seen.add(key)
                    candidates.append(cand)
    return candidates, errors
