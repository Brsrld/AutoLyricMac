#!/usr/bin/env python3
"""Fetch public-domain/CC0 photographs from Wikimedia Commons for the
Phase 0 prototypes, via the official MediaWiki API.

Only files whose extmetadata license is Public domain or CC0 are accepted.
Every download is recorded in References/proto_media/ATTRIBUTION.json with
source page, author, and license so provenance is auditable.

Usage: python fetch_proto_media.py
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = REPO_ROOT / "References" / "proto_media"

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "AutoLyricMac-prototype/0.1 (local development tool)"

ACCEPTED_LICENSES = {"public domain", "cc0", "pdm-owner", "pd-us", "no restrictions"}

# slug -> search query (Phase 0 scene needs)
WANTED = {
    # Archive Collage scenes (will be converted to monochrome)
    "train_smoke": "locomotive railroad Delano smoke",
    "railway_fog": "railway tracks fog",
    "lone_road": "Man walking on the highway Napa Valley",
    # Doodle Memory backgrounds (warm domestic/outdoor scenes)
    "kitchen_window": "farm kitchen interior stove Farm Security Administration",
    "park_bench": "park bench trees path",
    "living_room": "cottage interior room window light",
}

MIN_WIDTH = 1200


def api_get(params):
    query = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def license_ok(extmeta):
    short = (extmeta.get("LicenseShortName", {}).get("value") or "").lower()
    return any(acc in short for acc in ACCEPTED_LICENSES)


def search_candidates(query, limit=12):
    data = api_get({
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": 1800,
    })
    pages = (data.get("query") or {}).get("pages") or {}
    return sorted(pages.values(), key=lambda p: p.get("index", 99))


def pick_and_download(slug, query):
    for page in search_candidates(query):
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        extmeta = info.get("extmetadata") or {}
        if not license_ok(extmeta):
            continue
        if (info.get("width") or 0) < MIN_WIDTH:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        dest = MEDIA_DIR / f"{slug}.jpg"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            fh.write(resp.read())
        return {
            "slug": slug,
            "file": dest.name,
            "query": query,
            "title": page.get("title"),
            "source_page": extmeta.get("DescriptionUrl", {}).get("value")
                or info.get("descriptionurl"),
            "author": (extmeta.get("Artist", {}).get("value") or "unknown")[:200],
            "license": extmeta.get("LicenseShortName", {}).get("value"),
            "width": info.get("width"),
            "height": info.get("height"),
        }
    return None


def main():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    records, missing = [], []
    existing = {}
    attribution = MEDIA_DIR / "ATTRIBUTION.json"
    if attribution.exists():
        existing = {r["slug"]: r for r in json.loads(attribution.read_text())}
    for slug, query in WANTED.items():
        if slug in existing and (MEDIA_DIR / existing[slug]["file"]).exists():
            print(f"[skip] {slug}: already downloaded")
            records.append(existing[slug])
            continue
        time.sleep(2)  # stay well under Commons API rate limits
        record = pick_and_download(slug, query)
        if record:
            print(f"[ok] {slug}: {record['title']} ({record['license']})")
            records.append(record)
        else:
            print(f"[MISS] {slug}: no PD/CC0 result for '{query}'")
            missing.append(slug)
    (MEDIA_DIR / "ATTRIBUTION.json").write_text(json.dumps(records, indent=2))
    print(f"\n{len(records)} downloaded, {len(missing)} missing: {missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
