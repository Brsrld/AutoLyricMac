"""Candidate ranking (pure, unit-tested).

Scores provider results against what we asked for. The weights favor a
correct song match (title + artist + duration) over niceties (synced
timings), so a wrong-but-synced hit never beats the right song.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import LyricsCandidate

_PARENS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_NOISE = re.compile(
    r"\b(official|video|audio|lyrics?|lyric video|hd|4k|remaster(?:ed)?"
    r"|visualizer|mv|m/v|feat\.?|ft\.?)\b", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w\s]")


def normalize_title(s):
    """Fold case/accents and strip the usual YouTube-title noise."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _PARENS.sub(" ", s)
    s = _NOISE.sub(" ", s)
    s = _NON_WORD.sub(" ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _similarity(a, b):
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class RankedCandidate:
    candidate: LyricsCandidate
    score: float
    reasons: list[str]


def score_candidate(cand, artist, title, duration=None):
    """Score one candidate in 0..1 with human-readable reasoning."""
    reasons = []

    title_sim = _similarity(cand.title, title)
    reasons.append(f"title match {title_sim:.2f} ({cand.title!r})")

    artist_sim = _similarity(cand.artist, artist) if artist else 0.5
    if artist:
        reasons.append(f"artist match {artist_sim:.2f} ({cand.artist!r})")
    else:
        reasons.append("no artist requested; neutral artist score")

    if duration and cand.duration:
        delta = abs(cand.duration - duration)
        dur_score = max(0.0, 1.0 - delta / 15.0)
        reasons.append(f"duration off by {delta:.1f}s")
    else:
        dur_score = 0.5
        reasons.append("duration unknown; neutral duration score")

    synced_bonus = 1.0 if cand.synced else 0.0
    if cand.synced:
        reasons.append("has synchronized (LRC) timings")

    body = cand.plain_text or cand.lrc_text
    length_ok = 1.0 if len(body.strip()) >= 80 else 0.2
    if length_ok < 1.0 and not cand.instrumental:
        reasons.append("suspiciously short lyrics body")

    score = (0.35 * title_sim + 0.25 * artist_sim + 0.20 * dur_score
             + 0.15 * synced_bonus + 0.05 * length_ok)
    if cand.instrumental:
        score *= 0.1
        reasons.append("marked instrumental")
    return score, reasons


def rank_candidates(candidates, artist, title, duration=None, min_score=0.35):
    """Return RankedCandidates sorted best-first; drops hopeless matches."""
    ranked = []
    for cand in candidates:
        score, reasons = score_candidate(cand, artist, title, duration)
        if score >= min_score:
            ranked.append(RankedCandidate(cand, score, reasons))
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
