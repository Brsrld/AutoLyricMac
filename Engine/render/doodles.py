"""Procedural doodle assets for the Doodle Memory prototype.

Style contract (from Docs/REFERENCE_ANALYSIS.md): cream fill, dark-navy
imperfect hand-drawn outline, consistent stroke, simplified rounded forms,
minimal facial detail, transparent background. Paths are densified and
jittered so every edge wobbles like marker ink; drawn at 2x and downscaled.

This is the seed of the curated doodle library (full library in Phase 6).
"""

import math
import random

from PIL import Image, ImageDraw

NAVY = (29, 42, 82, 255)
CREAM = (240, 234, 211, 255)
CYAN = (127, 196, 201, 255)


def _densify(points, step=18, closed=False):
    """Insert points along each segment so jitter bends the edges too."""
    pts = list(points) + ([points[0]] if closed else [])
    out = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step))
        for i in range(n):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    out.append(pts[-1])
    return out


def _wobble(points, rng, amp):
    return [(x + rng.uniform(-amp, amp), y + rng.uniform(-amp, amp))
            for x, y in points]


def _stroke(draw, points, rng, width, color=NAVY, closed=False, amp=4.5):
    """Double-traced wobbly line — the imperfect hand-drawn stroke."""
    dense = _densify(points, closed=closed)
    for k in range(2):
        draw.line(_wobble(dense, rng, amp * (0.7 + 0.3 * k)),
                  fill=color, width=width, joint="curve")


def _blob(draw, points, rng, fill=CREAM, amp=4.0, closed=True):
    """Wobbly filled silhouette."""
    draw.polygon(_wobble(_densify(points, closed=closed), rng, amp), fill=fill)


def _ellipse_pts(cx, cy, rx, ry, n=36, start=0.0, end=2 * math.pi):
    return [(cx + rx * math.cos(start + (end - start) * i / n),
             cy + ry * math.sin(start + (end - start) * i / n))
            for i in range(n + 1)]


def _canvas(w, h):
    img = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _finish(img, w, h):
    return img.resize((w, h), Image.LANCZOS)


def standing_figure(height=760, seed=3):
    """Adult figure from behind, long dress, bob hair, arms at sides."""
    w = int(height * 0.56)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 58)

    head_r = H2 * 0.082
    cx, head_cy = W2 * 0.5, H2 * 0.145
    body_top = head_cy + head_r * 0.92
    body_bottom = H2 * 0.93
    shoulder = W2 * 0.27
    hem = W2 * 0.42

    dress = [(cx - shoulder * 0.75, body_top), (cx + shoulder * 0.75, body_top),
             (cx + shoulder, body_top + H2 * 0.10),
             (cx + hem, body_bottom), (cx - hem, body_bottom),
             (cx - shoulder, body_top + H2 * 0.10)]
    head = _ellipse_pts(cx, head_cy, head_r, head_r * 1.04)
    _blob(d, dress, rng)
    _blob(d, head, rng, amp=3.0)

    # hair: filled cap slightly larger than the head, drawn as its own blob
    hair = _ellipse_pts(cx, head_cy - head_r * 0.18, head_r * 1.22, head_r * 1.05,
                        start=math.pi * 0.92, end=math.pi * 2.08)
    hair += [(cx + head_r * 1.1, head_cy + head_r * 0.55),
             (cx - head_r * 1.1, head_cy + head_r * 0.55)]
    _blob(d, hair, rng, fill=CREAM, amp=3.0)
    _stroke(d, hair, rng, sw, closed=True, amp=3.0)
    # a few hair strands
    for fx in (-0.4, 0.0, 0.45):
        _stroke(d, [(cx + head_r * fx, head_cy - head_r * 0.9),
                    (cx + head_r * (fx + 0.08), head_cy - head_r * 0.2)],
                rng, max(6, sw - 4), amp=2.0)

    _stroke(d, head, rng, sw, closed=True, amp=3.0)
    _stroke(d, dress, rng, sw, closed=True)

    # arms hanging at the sides
    for side in (-1, 1):
        sx = cx + side * shoulder * 0.9
        _stroke(d, [(sx, body_top + H2 * 0.06),
                    (sx + side * W2 * 0.045, body_top + H2 * 0.22),
                    (sx + side * W2 * 0.02, body_top + H2 * 0.34)], rng, sw)
    return _finish(img, w, height)


def sitting_child(height=430, seed=11):
    """Small child sitting, legs dangling, simple happy face."""
    w = int(height * 0.82)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 40)

    head_r = H2 * 0.155
    cx, head_cy = W2 * 0.44, H2 * 0.19
    body = [(cx - W2 * 0.19, head_cy + head_r * 0.85),
            (cx + W2 * 0.21, head_cy + head_r * 0.85),
            (cx + W2 * 0.25, H2 * 0.60), (cx - W2 * 0.23, H2 * 0.60)]
    head = _ellipse_pts(cx, head_cy, head_r, head_r)
    _blob(d, body, rng)
    _blob(d, head, rng, amp=3.0)

    _stroke(d, head, rng, sw, closed=True, amp=3.0)
    # hair tufts
    for fx, fy in ((-0.45, -0.85), (0.0, -1.1), (0.4, -0.85)):
        _stroke(d, [(cx + head_r * fx, head_cy + head_r * fy),
                    (cx + head_r * fx * 0.5, head_cy - head_r * 0.45)],
                rng, max(6, sw - 4), amp=2.0)
    # dot eyes + smile
    er = sw * 0.7
    for ex in (cx - head_r * 0.38, cx + head_r * 0.30):
        d.ellipse((ex - er, head_cy - head_r * 0.1 - er,
                   ex + er, head_cy - head_r * 0.1 + er), fill=NAVY)
    _stroke(d, _ellipse_pts(cx - head_r * 0.05, head_cy + head_r * 0.3,
                            head_r * 0.34, head_r * 0.22,
                            start=0.15 * math.pi, end=0.85 * math.pi),
            rng, max(6, sw - 4), amp=1.5)
    _stroke(d, body, rng, sw, closed=True)
    # dangling legs with little feet
    for lx in (cx - W2 * 0.09, cx + W2 * 0.11):
        _stroke(d, [(lx, H2 * 0.60), (lx + W2 * 0.015, H2 * 0.84),
                    (lx + W2 * 0.085, H2 * 0.865)], rng, sw)
    # arms on lap
    _stroke(d, [(cx - W2 * 0.19, H2 * 0.38), (cx - W2 * 0.04, H2 * 0.50),
                (cx + W2 * 0.12, H2 * 0.48)], rng, sw)
    return _finish(img, w, height)


def hugging_pair(height=640, seed=21):
    """Parent crouching, child wrapped in their arms — two clear silhouettes."""
    w = int(height * 0.98)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 50)

    # parent: big rounded hunched silhouette (head + curved back)
    px, py = W2 * 0.36, H2 * 0.22
    pr = H2 * 0.105
    parent = [(px - W2 * 0.16, py + pr * 0.8),
              (px + W2 * 0.14, py + pr * 0.9),
              (px + W2 * 0.30, H2 * 0.52),
              (px + W2 * 0.26, H2 * 0.90),
              (px - W2 * 0.30, H2 * 0.90),
              (px - W2 * 0.26, H2 * 0.45)]
    phead = _ellipse_pts(px, py, pr, pr * 1.04)
    _blob(d, parent, rng)
    _blob(d, phead, rng, amp=3.0)

    # parent hair
    hair = _ellipse_pts(px, py - pr * 0.2, pr * 1.24, pr * 1.02,
                        start=math.pi * 0.9, end=math.pi * 2.1)
    hair += [(px + pr * 1.05, py + pr * 0.5), (px - pr * 1.05, py + pr * 0.5)]
    _blob(d, hair, rng, amp=3.0)
    _stroke(d, hair, rng, sw, closed=True, amp=3.0)
    _stroke(d, phead, rng, sw, closed=True, amp=3.0)
    _stroke(d, parent, rng, sw, closed=True)

    # child: smaller figure tucked against parent's chest, facing them
    sx, sy = W2 * 0.63, H2 * 0.38
    sr = H2 * 0.075
    child = [(sx - W2 * 0.10, sy + sr * 0.8), (sx + W2 * 0.13, sy + sr * 0.9),
             (sx + W2 * 0.16, H2 * 0.82), (sx - W2 * 0.08, H2 * 0.82)]
    chead = _ellipse_pts(sx, sy, sr, sr)
    _blob(d, child, rng)
    _blob(d, chead, rng, amp=2.5)
    _stroke(d, chead, rng, sw, closed=True, amp=2.5)
    # child hair tuft + closed happy eyes
    _stroke(d, [(sx - sr * 0.3, sy - sr * 1.05), (sx, sy - sr * 1.3),
                (sx + sr * 0.3, sy - sr * 1.0)], rng, max(6, sw - 4), amp=2.0)
    for ex in (sx - sr * 0.35, sx + sr * 0.3):
        _stroke(d, _ellipse_pts(ex, sy - sr * 0.05, sr * 0.16, sr * 0.10,
                                start=0.1 * math.pi, end=0.9 * math.pi),
                rng, max(6, sw - 4), amp=1.0)
    _stroke(d, child, rng, sw, closed=True)

    # parent's arm wrapping around the child's back — one clear curve
    arm = _ellipse_pts(sx - W2 * 0.02, sy + sr * 1.6, W2 * 0.20, H2 * 0.14,
                       start=-0.35 * math.pi, end=0.75 * math.pi)
    _stroke(d, arm, rng, sw, amp=3.0)
    return _finish(img, w, height)


def sun(size=340, seed=5):
    img, d = _canvas(size, size)
    rng = random.Random(seed)
    S2 = size * 2
    sw = max(8, S2 // 32)
    cx = cy = S2 / 2
    r = S2 * 0.26
    disk = _ellipse_pts(cx, cy, r, r)
    _blob(d, disk, rng, fill=(244, 224, 96, 255), amp=3.0)
    _stroke(d, disk, rng, sw, closed=True, amp=3.0)
    for i in range(9):
        a = i / 9 * 2 * math.pi + 0.2
        r0, r1 = r * 1.16, r * 1.55 + rng.uniform(-8, 12)
        _stroke(d, [(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                    (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
                rng, sw, amp=2.5)
    return _finish(img, size, size)


def steam_squiggle(height=300, seed=9, color=CYAN):
    """Rising wobbly steam curls (kettle / sink)."""
    w = int(height * 0.62)
    img, d = _canvas(w, height)
    rng = random.Random(seed)
    W2, H2 = w * 2, height * 2
    sw = max(8, H2 // 32)
    for k in range(3):
        x0 = W2 * (0.25 + 0.25 * k)
        pts = [(x0 + math.sin(t / 13 * math.pi * 2.6 + k) * W2 * 0.10,
                H2 * (0.95 - 0.9 * t / 13)) for t in range(14)]
        _stroke(d, pts, rng, sw, color=color, amp=3.0)
    return _finish(img, w, height)


def raindrops(size=420, seed=13, color=CYAN):
    img, d = _canvas(size, size)
    rng = random.Random(seed)
    S2 = size * 2
    sw = max(8, S2 // 38)
    for i in range(7):
        x = S2 * (0.12 + 0.13 * i) + rng.uniform(-14, 14)
        y = S2 * (0.2 + 0.55 * ((i * 37) % 100) / 100)
        h = S2 * 0.10
        _stroke(d, [(x, y), (x - h * 0.28, y + h),
                    (x + h * 0.28, y + h * 0.95), (x, y)],
                rng, sw, color=color, amp=2.5)
    return _finish(img, size, size)
