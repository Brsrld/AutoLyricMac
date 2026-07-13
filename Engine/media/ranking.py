"""Media candidate ranking and rejection (pure, unit-tested).

Enforces the licensing/quality contract: reject media that would need
upscaling or stretching, watermark/logo/text-heavy items, and wrong kinds;
rank the rest by semantic relevance to the scene, orientation, resolution
headroom, and (for video) usable duration.
"""

import re
from dataclasses import dataclass

OUT_W, OUT_H = 1080, 1920

# photos should be substantially above output size (no enlargement)
MIN_PHOTO_PORTRAIT = (1080, 1600)
MIN_PHOTO_ANY = 1400            # smallest edge for landscape adaptation
MIN_VIDEO_HEIGHT = 1080

_BAD_TAGS = re.compile(r"\b(watermark|logo|copyright|brand|advert|banner|"
                       r"template|mockup|infographic|screenshot|text overlay)\b",
                       re.IGNORECASE)


@dataclass
class RankedMedia:
    candidate: object
    score: float
    reasons: list


def _tokens(text):
    return set(re.findall(r"[a-zğüşıöç]+", (text or "").lower())) - {
        "the", "a", "an", "of", "on", "in", "and", "with", "at", "to"}


def reject_reason(cand, scene_duration=None):
    """Why a candidate must not be used, or None if acceptable."""
    if _BAD_TAGS.search(cand.tags or ""):
        return "looks watermarked/branded/text-heavy"
    if cand.kind == "photo":
        if cand.portrait:
            if cand.width < MIN_PHOTO_PORTRAIT[0] or cand.height < MIN_PHOTO_PORTRAIT[1]:
                return f"too small ({cand.width}x{cand.height}) — would need enlargement"
        else:
            if min(cand.width, cand.height) < MIN_PHOTO_ANY:
                return f"too small for landscape adaptation ({cand.width}x{cand.height})"
    elif cand.kind == "video":
        if cand.height < MIN_VIDEO_HEIGHT:
            return f"video below 1080 vertical ({cand.width}x{cand.height})"
        if scene_duration and cand.duration and cand.duration < scene_duration * 0.8:
            return f"video too short ({cand.duration:.1f}s for a {scene_duration:.1f}s scene)"
    else:
        return f"unsupported kind {cand.kind!r}"
    return None


def score_media(cand, scene):
    """0..1 score with reasoning for an accepted candidate."""
    reasons = []

    scene_tokens = _tokens(" ".join(scene.get("queries", [])
                                    + scene.get("subjects", [])
                                    + [scene.get("lyric") or ""]))
    cand_tokens = _tokens(f"{cand.tags} {cand.query}")
    overlap = len(scene_tokens & cand_tokens)
    relevance = min(1.0, overlap / 4.0)
    reasons.append(f"relevance {relevance:.2f} ({overlap} shared terms)")

    if cand.portrait:
        orientation = 1.0
        reasons.append("portrait orientation")
    elif cand.width == cand.height:
        orientation = 0.6
        reasons.append("square (needs framing)")
    else:
        orientation = 0.35
        reasons.append("landscape (needs crop/fill adaptation)")

    if cand.kind == "photo":
        headroom = min(cand.width / OUT_W, cand.height / OUT_H)
    else:
        headroom = cand.height / OUT_H if cand.portrait else cand.height / OUT_W
    resolution = min(1.0, max(0.0, (headroom - 0.8) / 1.2))
    reasons.append(f"resolution headroom {headroom:.2f}x")

    provider_pref = {"pexels": 1.0, "pixabay": 0.9, "unsplash": 0.85}.get(
        cand.provider, 0.7)

    score = (0.45 * relevance + 0.25 * orientation + 0.20 * resolution
             + 0.10 * provider_pref)
    return score, reasons


def rank_media(candidates, scene, scene_duration=None):
    """(accepted RankedMedia sorted best-first, rejected [(cand, reason)])."""
    accepted, rejected = [], []
    for cand in candidates:
        reason = reject_reason(cand, scene_duration)
        if reason is not None:
            rejected.append((cand, reason))
            continue
        score, reasons = score_media(cand, scene)
        accepted.append(RankedMedia(cand, score, reasons))
    accepted.sort(key=lambda r: r.score, reverse=True)
    return accepted, rejected
