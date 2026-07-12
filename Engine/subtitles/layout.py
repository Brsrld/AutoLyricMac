"""Subtitle layout: wrapping, safe zones, dynamic placement (pure).

Text measurement is injected as a callable so all wrapping/placement logic
is unit-testable without fonts or Pillow. Coordinates are 1080x1920 canvas
pixels. The safe zone keeps subtitles away from phone UI: status/top overlays,
the right-hand interaction rail, and the bottom caption/navigation area.
"""

import random
from dataclasses import dataclass

CANVAS_W, CANVAS_H = 1080, 1920


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def intersects(self, other):
        return not (self.right <= other.x or other.right <= self.x
                    or self.bottom <= other.y or other.bottom <= self.y)

    def overlap_area(self, other):
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0.0, dx) * max(0.0, dy)

    def contains_rect(self, other):
        return (other.x >= self.x and other.y >= self.y
                and other.right <= self.right and other.bottom <= self.bottom)


# Away from top overlays (~260px), right interaction rail (~190px), and the
# bottom caption/nav area (~340px) — per the product spec's readability rule.
SAFE_ZONE = Rect(70, 260, CANVAS_W - 70 - 190, CANVAS_H - 260 - 340)


def wrap_text(text, max_width, measure):
    """Greedy word wrap using an injected `measure(str) -> px` callable.

    Never returns a line wider than `max_width` unless a single word alone
    exceeds it — such a word is force-broken with a hyphen so nothing can
    ever escape the safe zone.
    """
    words = [w for w in (text or "").split() if w]
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and measure(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
        if measure(current) > max_width:  # a single word wider than the zone
            chunks = _force_break(current, max_width, measure)
            lines.extend(chunks[:-1])
            current = chunks[-1]
    if current:
        lines.append(current)
    return lines


def _force_break(word, max_width, measure):
    chunks, piece = [], ""
    for ch in word:
        trial = piece + ch + "-"
        if measure(trial) > max_width and piece:
            chunks.append(piece + "-")
            piece = ch
        else:
            piece += ch
    chunks.append(piece)
    return chunks


def block_size(lines, measure, line_height, line_gap=8):
    """(w, h) of a wrapped block for placement."""
    if not lines:
        return 0, 0
    w = max(measure(ln) for ln in lines)
    h = len(lines) * line_height + (len(lines) - 1) * line_gap
    return w, h


def place_block(size, avoid=(), zone=SAFE_ZONE, preferred="lower", seed=0):
    """Choose (x, y) for a block of `size` inside the safe zone.

    Deterministic for a given seed. Tries the preferred vertical band first
    (with seeded jitter so placement varies line-to-line), then the other
    bands; skips positions colliding with `avoid` rects (faces / focal
    subjects); falls back to the candidate with least overlap. Returns a Rect.
    """
    w, h = size
    w, h = min(w, zone.w), min(h, zone.h)
    rng = random.Random(seed)

    bands = {"lower": 0.78, "center": 0.5, "upper": 0.28}
    order = [preferred] + [b for b in ("lower", "center", "upper")
                           if b != preferred]

    candidates = []
    for band in order:
        cy = zone.y + bands[band] * zone.h
        for _ in range(4):
            jx = rng.uniform(-0.08, 0.08) * zone.w
            jy = rng.uniform(-0.05, 0.05) * zone.h
            x = zone.x + (zone.w - w) / 2 + jx
            y = cy - h / 2 + jy
            x = min(max(x, zone.x), zone.right - w)
            y = min(max(y, zone.y), zone.bottom - h)
            candidates.append(Rect(x, y, w, h))

    for rect in candidates:
        if not any(rect.intersects(a) for a in avoid):
            return rect
    return min(candidates,
               key=lambda r: sum(r.overlap_area(a) for a in avoid))
