"""Curated procedural doodle library (Phase 6).

Every asset follows the style contract: cream/white fill, dark-navy
imperfect hand-drawn outline, consistent stroke, simplified rounded forms,
minimal facial detail, transparent background. Assets are deterministic
(seeded), built on the Phase 0 primitives in `doodles.py`, and looked up by
semantic tags so the renderer can match a scene's subjects to a doodle.

`pick_doodle(subjects, index)` is pure and unit-testable.
"""

import math
import random

from PIL import ImageDraw

from doodles import (CREAM, CYAN, NAVY, _blob, _canvas, _ellipse_pts,
                     _finish, _stroke, hugging_pair, raindrops, sitting_child,
                     standing_figure, steam_squiggle, sun)


# ---------------------------------------------------------------------------
# New builders (same visual contract as doodles.py)
# ---------------------------------------------------------------------------

def walking_figure(height=720, seed=31):
    """Side-view figure mid-stride, coat and bag — journeys and distance."""
    w = int(height * 0.6)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 56)

    head_r = H2 * 0.08
    cx, head_cy = W2 * 0.52, H2 * 0.14
    coat = [(cx - W2 * 0.16, head_cy + head_r),
            (cx + W2 * 0.17, head_cy + head_r),
            (cx + W2 * 0.22, H2 * 0.62), (cx - W2 * 0.20, H2 * 0.62)]
    head = _ellipse_pts(cx + W2 * 0.03, head_cy, head_r, head_r * 1.02)
    _blob(d, coat, rng)
    _blob(d, head, rng, amp=3.0)
    _stroke(d, head, rng, sw, closed=True, amp=3.0)
    _stroke(d, coat, rng, sw, closed=True)
    # striding legs
    hip = (cx, H2 * 0.62)
    _stroke(d, [hip, (cx - W2 * 0.14, H2 * 0.82), (cx - W2 * 0.20, H2 * 0.94),
                (cx - W2 * 0.11, H2 * 0.945)], rng, sw)
    _stroke(d, [hip, (cx + W2 * 0.12, H2 * 0.80), (cx + W2 * 0.10, H2 * 0.95),
                (cx + W2 * 0.20, H2 * 0.95)], rng, sw)
    # swinging arm + small bag
    _stroke(d, [(cx + W2 * 0.10, H2 * 0.30), (cx + W2 * 0.20, H2 * 0.44)],
            rng, sw)
    bag = _ellipse_pts(cx + W2 * 0.22, H2 * 0.50, W2 * 0.06, H2 * 0.045)
    _blob(d, bag, rng, amp=2.0)
    _stroke(d, bag, rng, max(6, sw - 4), closed=True, amp=2.0)
    return _finish(img, w, height)


def talking_pair(height=620, seed=37):
    """Two figures facing each other, one gesturing — conversation."""
    w = int(height * 0.95)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 52)
    for side, fx in ((-1, 0.30), (1, 0.70)):
        head_r = H2 * 0.085
        cx, head_cy = W2 * fx, H2 * 0.20
        body = [(cx - W2 * 0.11, head_cy + head_r * 0.9),
                (cx + W2 * 0.11, head_cy + head_r * 0.9),
                (cx + W2 * 0.13, H2 * 0.9),
                (cx - W2 * 0.13, H2 * 0.9)]
        head = _ellipse_pts(cx + side * head_r * 0.15, head_cy,
                            head_r, head_r * 1.03)
        _blob(d, body, rng)
        _blob(d, head, rng, amp=3.0)
        _stroke(d, head, rng, sw, closed=True, amp=3.0)
        _stroke(d, body, rng, sw, closed=True)
    # gesturing arm + a little speech curl
    _stroke(d, [(W2 * 0.38, H2 * 0.40), (W2 * 0.50, H2 * 0.34)], rng, sw)
    _stroke(d, _ellipse_pts(W2 * 0.52, H2 * 0.16, W2 * 0.05, H2 * 0.035,
                            start=0.2, end=5.6), rng, max(6, sw - 4), amp=2.0)
    return _finish(img, w, height)


def playing_child(height=520, seed=41):
    """Child running after a ball — play and joy."""
    w = int(height * 1.0)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 44)
    head_r = H2 * 0.12
    cx, head_cy = W2 * 0.38, H2 * 0.22
    body = [(cx - W2 * 0.10, head_cy + head_r * 0.85),
            (cx + W2 * 0.12, head_cy + head_r * 0.85),
            (cx + W2 * 0.14, H2 * 0.60), (cx - W2 * 0.10, H2 * 0.62)]
    head = _ellipse_pts(cx, head_cy, head_r, head_r)
    _blob(d, body, rng)
    _blob(d, head, rng, amp=3.0)
    _stroke(d, head, rng, sw, closed=True, amp=3.0)
    # smile + hair tuft
    _stroke(d, _ellipse_pts(cx, head_cy + head_r * 0.25, head_r * 0.3,
                            head_r * 0.2, start=0.15 * math.pi,
                            end=0.85 * math.pi), rng, max(6, sw - 4), amp=1.2)
    _stroke(d, [(cx - head_r * 0.2, head_cy - head_r * 1.05),
                (cx + head_r * 0.15, head_cy - head_r * 1.25)],
            rng, max(6, sw - 4), amp=1.5)
    _stroke(d, body, rng, sw, closed=True)
    # running legs + reaching arms
    _stroke(d, [(cx, H2 * 0.61), (cx - W2 * 0.10, H2 * 0.82),
                (cx - W2 * 0.16, H2 * 0.92)], rng, sw)
    _stroke(d, [(cx + W2 * 0.06, H2 * 0.60), (cx + W2 * 0.16, H2 * 0.78),
                (cx + W2 * 0.13, H2 * 0.93)], rng, sw)
    _stroke(d, [(cx + W2 * 0.10, H2 * 0.34), (cx + W2 * 0.26, H2 * 0.42)],
            rng, sw)
    # ball ahead of the child
    ball = _ellipse_pts(W2 * 0.78, H2 * 0.78, W2 * 0.09, W2 * 0.09)
    _blob(d, ball, rng, amp=2.5)
    _stroke(d, ball, rng, sw, closed=True, amp=2.5)
    _stroke(d, _ellipse_pts(W2 * 0.78, H2 * 0.78, W2 * 0.09, W2 * 0.03,
                            start=0.1, end=3.0), rng, max(6, sw - 4), amp=1.5)
    return _finish(img, w, height)


def window_frame(height=560, seed=43):
    """Four-pane window with curtains — home, waiting, sky."""
    w = int(height * 0.78)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 50)
    frame = [(W2 * 0.12, H2 * 0.06), (W2 * 0.88, H2 * 0.06),
             (W2 * 0.88, H2 * 0.94), (W2 * 0.12, H2 * 0.94)]
    _blob(d, frame, rng, fill=(252, 250, 244, 235), amp=3.0)
    _stroke(d, frame, rng, sw, closed=True)
    _stroke(d, [(W2 * 0.5, H2 * 0.07), (W2 * 0.5, H2 * 0.93)], rng, sw, amp=2.5)
    _stroke(d, [(W2 * 0.13, H2 * 0.5), (W2 * 0.87, H2 * 0.5)], rng, sw, amp=2.5)
    # curtains hinted at the corners
    for side in (0, 1):
        x0 = W2 * (0.12 if side == 0 else 0.88)
        pts = [(x0, H2 * 0.06)]
        for k in range(1, 6):
            pts.append((x0 + (1 if side == 0 else -1) * W2 * 0.05 *
                        math.sin(k * 1.1), H2 * (0.06 + 0.16 * k)))
        _stroke(d, pts, rng, max(6, sw - 4), amp=3.0)
    return _finish(img, w, height)


def little_house(height=480, seed=47):
    """Small house with chimney smoke — home."""
    w = int(height * 1.0)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 44)
    body = [(W2 * 0.18, H2 * 0.45), (W2 * 0.82, H2 * 0.45),
            (W2 * 0.82, H2 * 0.92), (W2 * 0.18, H2 * 0.92)]
    roof = [(W2 * 0.10, H2 * 0.47), (W2 * 0.5, H2 * 0.10),
            (W2 * 0.90, H2 * 0.47)]
    _blob(d, body, rng)
    _blob(d, roof, rng)
    _stroke(d, body, rng, sw, closed=True)
    _stroke(d, roof, rng, sw, closed=True)
    # door + window
    door = [(W2 * 0.44, H2 * 0.92), (W2 * 0.44, H2 * 0.66),
            (W2 * 0.56, H2 * 0.66), (W2 * 0.56, H2 * 0.92)]
    _stroke(d, door, rng, max(6, sw - 2))
    win = _ellipse_pts(W2 * 0.30, H2 * 0.58, W2 * 0.055, W2 * 0.055)
    _stroke(d, win, rng, max(6, sw - 2), closed=True, amp=2.0)
    # chimney + smoke curls
    _stroke(d, [(W2 * 0.68, H2 * 0.28), (W2 * 0.68, H2 * 0.14),
                (W2 * 0.76, H2 * 0.14), (W2 * 0.76, H2 * 0.33)], rng, sw)
    for k in range(2):
        _stroke(d, _ellipse_pts(W2 * (0.72 + 0.04 * k), H2 * (0.08 - 0.045 * k),
                                W2 * 0.035, H2 * 0.02, start=0.3, end=5.8),
                rng, max(6, sw - 4), amp=2.0)
    return _finish(img, w, height)


def candle_flame(height=420, seed=53):
    """Candle with warm flame — fire, warmth, memory."""
    w = int(height * 0.55)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 40)
    body = [(W2 * 0.34, H2 * 0.38), (W2 * 0.66, H2 * 0.38),
            (W2 * 0.64, H2 * 0.92), (W2 * 0.36, H2 * 0.92)]
    _blob(d, body, rng)
    _stroke(d, body, rng, sw, closed=True)
    flame = [(W2 * 0.5, H2 * 0.10), (W2 * 0.60, H2 * 0.22),
             (W2 * 0.56, H2 * 0.32), (W2 * 0.44, H2 * 0.32),
             (W2 * 0.40, H2 * 0.22)]
    _blob(d, flame, rng, fill=(244, 224, 96, 255), amp=2.5)
    _stroke(d, flame, rng, max(6, sw - 2), closed=True, amp=2.5)
    _stroke(d, [(W2 * 0.5, H2 * 0.32), (W2 * 0.5, H2 * 0.38)], rng,
            max(6, sw - 2))
    return _finish(img, w, height)


def moon_stars(size=380, seed=59):
    """Full moon with sleepy face and small stars — night, dreams."""
    img, d = _canvas(size, size)
    rng = random.Random(seed)
    S2 = size * 2
    sw = max(8, S2 // 34)
    cx, cy, r = S2 * 0.42, S2 * 0.5, S2 * 0.27
    moon = _ellipse_pts(cx, cy, r, r)
    _blob(d, moon, rng, amp=3.0)
    _stroke(d, moon, rng, sw, closed=True, amp=3.0)
    # closed sleepy eyes + tiny craters
    for ex in (cx - r * 0.35, cx + r * 0.3):
        _stroke(d, _ellipse_pts(ex, cy - r * 0.1, r * 0.16, r * 0.10,
                                start=0.1 * math.pi, end=0.9 * math.pi),
                rng, max(6, sw - 4), amp=1.0)
    for fx, fy in ((-0.4, 0.45), (0.35, 0.5)):
        _stroke(d, _ellipse_pts(cx + r * fx, cy + r * fy, r * 0.10, r * 0.08),
                rng, max(6, sw - 4), closed=True, amp=1.0)
    for fx, fy in ((0.78, 0.22), (0.86, 0.5), (0.72, 0.76)):
        x, y, s = S2 * fx, S2 * fy, S2 * 0.035
        _stroke(d, [(x - s, y), (x + s, y)], rng, max(6, sw - 4), amp=1.5)
        _stroke(d, [(x, y - s), (x, y + s)], rng, max(6, sw - 4), amp=1.5)
    return _finish(img, size, size)


def stone_pile(height=300, seed=61):
    """Three stacked rounded stones."""
    w = int(height * 1.25)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 34)
    for (fx, fy, rx, ry) in ((0.5, 0.78, 0.34, 0.18), (0.42, 0.5, 0.22, 0.14),
                             (0.52, 0.28, 0.14, 0.10)):
        stone = _ellipse_pts(W2 * fx, H2 * fy, W2 * rx, H2 * ry)
        _blob(d, stone, rng, fill=(233, 228, 214, 255), amp=3.5)
        _stroke(d, stone, rng, sw, closed=True, amp=3.5)
    return _finish(img, w, height)


def lonely_bench(height=460, seed=67):
    """Empty park bench — loneliness, waiting."""
    w = int(height * 1.35)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 42)
    seat = [(W2 * 0.10, H2 * 0.52), (W2 * 0.90, H2 * 0.52),
            (W2 * 0.90, H2 * 0.62), (W2 * 0.10, H2 * 0.62)]
    back = [(W2 * 0.12, H2 * 0.18), (W2 * 0.88, H2 * 0.18),
            (W2 * 0.88, H2 * 0.28), (W2 * 0.12, H2 * 0.28)]
    for part in (seat, back):
        _blob(d, part, rng, amp=3.0)
        _stroke(d, part, rng, sw, closed=True, amp=3.0)
    for fx in (0.18, 0.82):
        _stroke(d, [(W2 * fx, H2 * 0.28), (W2 * fx, H2 * 0.52)], rng, sw)
        _stroke(d, [(W2 * fx, H2 * 0.62), (W2 * fx, H2 * 0.92)], rng, sw)
        _stroke(d, [(W2 * fx - W2 * 0.05, H2 * 0.92),
                    (W2 * fx + W2 * 0.05, H2 * 0.92)], rng, sw, amp=2.0)
    return _finish(img, w, height)


def open_road(height=420, seed=71):
    """Road narrowing to the horizon with a small signpost — distance."""
    w = int(height * 0.9)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 42)
    road = [(W2 * 0.16, H2 * 0.94), (W2 * 0.84, H2 * 0.94),
            (W2 * 0.58, H2 * 0.14), (W2 * 0.44, H2 * 0.14)]
    _blob(d, road, rng, fill=(250, 247, 240, 220), amp=3.0)
    _stroke(d, road, rng, sw, closed=True)
    # dashed center line
    for k in range(4):
        t0, t1 = 0.14 + k * 0.20, 0.24 + k * 0.20
        x0 = W2 * (0.5 + 0.0)
        _stroke(d, [(x0, H2 * (0.94 - t0 * 0.8)), (x0, H2 * (0.94 - t1 * 0.8))],
                rng, max(6, sw - 4), amp=1.5)
    # signpost
    _stroke(d, [(W2 * 0.82, H2 * 0.55), (W2 * 0.82, H2 * 0.30)], rng, sw)
    sign = [(W2 * 0.76, H2 * 0.30), (W2 * 0.92, H2 * 0.30),
            (W2 * 0.92, H2 * 0.22), (W2 * 0.76, H2 * 0.22)]
    _blob(d, sign, rng, amp=2.0)
    _stroke(d, sign, rng, max(6, sw - 2), closed=True, amp=2.0)
    return _finish(img, w, height)


def photo_frame(height=430, seed=73):
    """Small standing photo frame with a heart — memory."""
    w = int(height * 0.8)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 40)
    outer = [(W2 * 0.14, H2 * 0.10), (W2 * 0.86, H2 * 0.10),
             (W2 * 0.86, H2 * 0.80), (W2 * 0.14, H2 * 0.80)]
    inner = [(W2 * 0.24, H2 * 0.20), (W2 * 0.76, H2 * 0.20),
             (W2 * 0.76, H2 * 0.70), (W2 * 0.24, H2 * 0.70)]
    _blob(d, outer, rng)
    _stroke(d, outer, rng, sw, closed=True)
    _stroke(d, inner, rng, max(6, sw - 2), closed=True, amp=2.5)
    heart = [(W2 * 0.5, H2 * 0.58), (W2 * 0.36, H2 * 0.42),
             (W2 * 0.42, H2 * 0.32), (W2 * 0.5, H2 * 0.38),
             (W2 * 0.58, H2 * 0.32), (W2 * 0.64, H2 * 0.42)]
    _stroke(d, heart, rng, max(6, sw - 2), closed=True, amp=2.0)
    # little stand
    _stroke(d, [(W2 * 0.5, H2 * 0.80), (W2 * 0.38, H2 * 0.94)], rng, sw)
    _stroke(d, [(W2 * 0.5, H2 * 0.80), (W2 * 0.62, H2 * 0.94)], rng, sw)
    return _finish(img, w, height)


def flying_birds(height=260, seed=79):
    """Three simple v-shaped birds — sky, hope, freedom."""
    w = int(height * 1.6)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 26)
    for fx, fy, s in ((0.25, 0.55, 1.0), (0.55, 0.30, 0.8), (0.78, 0.62, 0.65)):
        x, y = W2 * fx, H2 * fy
        span = W2 * 0.11 * s
        _stroke(d, [(x - span, y), (x - span * 0.3, y - H2 * 0.12 * s),
                    (x, y)], rng, sw, amp=2.0)
        _stroke(d, [(x, y), (x + span * 0.3, y - H2 * 0.12 * s),
                    (x + span, y)], rng, sw, amp=2.0)
    return _finish(img, w, height)


def reunion_pair(height=640, seed=83):
    """Two figures rushing together, arms open — reunion."""
    w = int(height * 1.0)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 52)
    for side, fx in ((-1, 0.28), (1, 0.72)):
        head_r = H2 * 0.085
        cx, head_cy = W2 * fx, H2 * 0.20
        lean = side * W2 * 0.05
        body = [(cx - W2 * 0.11 + lean, head_cy + head_r * 0.9),
                (cx + W2 * 0.11 + lean, head_cy + head_r * 0.9),
                (cx + W2 * 0.10 + lean * 2.4, H2 * 0.88),
                (cx - W2 * 0.12 + lean * 2.4, H2 * 0.88)]
        head = _ellipse_pts(cx + lean, head_cy, head_r, head_r * 1.02)
        _blob(d, body, rng)
        _blob(d, head, rng, amp=3.0)
        _stroke(d, head, rng, sw, closed=True, amp=3.0)
        _stroke(d, body, rng, sw, closed=True)
        # open arms towards the middle
        _stroke(d, [(cx + side * W2 * 0.08, H2 * 0.34),
                    (cx + side * W2 * 0.22, H2 * 0.28)], rng, sw)
    return _finish(img, w, height)


# ---------------------------------------------------------------------------
# Registry + pure selection
# ---------------------------------------------------------------------------

# name -> (builder, semantic tags, ground_anchored)
LIBRARY = {
    "standing_figure": (standing_figure,
                        ("person", "solitude", "waiting", "youth"), True),
    "walking_figure": (walking_figure,
                       ("walking", "journey", "road", "distance"), True),
    "talking_pair": (talking_pair, ("friends", "family", "talking"), True),
    "sitting_child": (sitting_child, ("child", "childhood", "play"), True),
    "hugging_pair": (hugging_pair,
                     ("embrace", "love", "mother", "father", "family",
                      "reunion"), True),
    "playing_child": (playing_child, ("play", "child", "childhood"), True),
    "reunion_pair": (reunion_pair, ("reunion", "farewell", "friends"), True),
    "lonely_bench": (lonely_bench, ("solitude", "waiting", "age"), True),
    "window_frame": (window_frame, ("window", "home", "waiting"), False),
    "little_house": (little_house, ("home", "house", "warmth"), True),
    "candle_flame": (candle_flame, ("fire", "warmth", "memory", "time"), True),
    "sun": (sun, ("sun", "light", "sky", "day"), False),
    "moon_stars": (moon_stars, ("moon", "stars", "night", "night sky",
                                "dream"), False),
    "stone_pile": (stone_pile, ("stone", "earth"), True),
    "open_road": (open_road, ("road", "distance", "journey"), True),
    "photo_frame": (photo_frame, ("memory", "letters", "heart", "love"), True),
    "flying_birds": (flying_birds, ("sky", "wind", "dream"), False),
    "steam_squiggle": (steam_squiggle, ("kitchen", "cooking", "warmth"),
                       False),
    "raindrops": (raindrops, ("rain", "water", "sea", "tears"), False),
}

# loose synonyms so LLM/loose subjects still hit library tags
_SYNONYMS = {"bird": "sky", "birds": "sky", "nightingale": "sky",
             "kuş": "sky", "bülbül": "sky", "gül": "flowers",
             "rose": "flowers", "mountain": "stone", "dağ": "stone",
             "village": "home", "köy": "home", "pencere": "window",
             "yol": "road", "gece": "night", "ay": "moon"}


def pick_doodle(subjects, index):
    """Best-matching doodle for a scene's subjects, or None (pure).

    A doodle only appears when it genuinely relates to the lyric line —
    no match means NO doodle (an unrelated bird/window/figure is worse
    than none). Ties break deterministically by index for variety.
    """
    subjects = [_SYNONYMS.get(s.lower(), s.lower())
                for s in (subjects or [])]
    scored = []
    for name, (_builder, tags, _ground) in LIBRARY.items():
        overlap = sum(1 for s in subjects if s in tags)
        if overlap:
            scored.append((overlap, name))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    best = [name for score, name in scored if score == scored[0][0]]
    return best[index % len(best)]


def build_doodle(name, height=640, seed_offset=0):
    """Instantiate a library doodle at roughly `height` px (RGBA).

    Different `seed_offset`s re-jitter every stroke — cycling a few
    variants at ~6 fps recreates the hand-drawn 'wiggle' of the reference
    videos."""
    builder, _tags, _ground = LIBRARY[name]
    import inspect
    kwargs = {}
    sig = inspect.signature(builder)
    if "seed" in sig.parameters and seed_offset:
        kwargs["seed"] = sig.parameters["seed"].default + seed_offset
    try:
        return builder(height=height, **kwargs)
    except TypeError:
        return builder(size=height, **kwargs)


def is_ground_anchored(name):
    return LIBRARY[name][2]
