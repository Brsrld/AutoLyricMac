"""Subject-aware cropping and landscape adaptation (Phase 4).

Never stretch: a 9:16 target is met by (a) cropping around the attention
subject when enough resolution remains, (b) blurred self-fill behind the
original framing, or (c) a layered/framed composition (Archive style default,
which places photos as framed objects anyway).

The attention map is deliberately simple and local: gradient magnitude
(detail) + saturation, softened by a center prior. It is not face detection —
it just keeps crops away from empty sky/walls and onto the busy subject.
"""

import numpy as np
from PIL import Image

TARGET_ASPECT = 9 / 16
MIN_CROP_HEIGHT = 1600      # crop result may be upscaled at most ~1.2x
UPSCALE_TOLERANCE = 1.2


def attention_map(img, width=64):
    """Small float32 map (h, w) of visual interest in 0..1."""
    scale = width / img.width
    small = img.convert("RGB").resize(
        (width, max(8, int(img.height * scale))), Image.BILINEAR)
    arr = np.asarray(small, dtype=np.float32) / 255.0

    gray = arr.mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    detail = gx + gy

    saturation = arr.max(axis=2) - arr.min(axis=2)

    h, w = gray.shape
    ys = (np.arange(h, dtype=np.float32)[:, None] - h / 2) / (h / 2)
    xs = (np.arange(w, dtype=np.float32)[None, :] - w / 2) / (w / 2)
    center_prior = 1.0 - 0.35 * np.sqrt(xs * xs + ys * ys).clip(0, 1)

    amap = (detail * 2.0 + saturation * 0.6) * center_prior
    peak = float(amap.max())
    return amap / peak if peak > 0 else amap


def subject_crop(img, aspect=TARGET_ASPECT):
    """Best crop rect (x, y, w, h) of `aspect` in original pixel coords.

    Scans candidate windows over the attention map and keeps the one with
    the highest attention mass. Deterministic.
    """
    amap = attention_map(img)
    mh, mw = amap.shape
    # window size in map coordinates, capped to the map
    if mw / mh > aspect:            # image wider than target: full height
        wh = mh
        ww = max(2, int(round(mh * aspect)))
    else:                           # image taller: full width
        ww = mw
        wh = max(2, int(round(mw / aspect)))
    ww, wh = min(ww, mw), min(wh, mh)

    integral = amap.cumsum(axis=0).cumsum(axis=1)

    def mass(x, y):
        x1, y1 = x + ww - 1, y + wh - 1
        total = integral[y1, x1]
        if x > 0:
            total -= integral[y1, x - 1]
        if y > 0:
            total -= integral[y - 1, x1]
        if x > 0 and y > 0:
            total += integral[y - 1, x - 1]
        return total

    best, best_xy = -1.0, (0, 0)
    steps = 24
    for sx in range(steps + 1):
        x = round(sx * (mw - ww) / steps) if mw > ww else 0
        for sy in range(steps + 1):
            y = round(sy * (mh - wh) / steps) if mh > wh else 0
            m = mass(x, y)
            if m > best:
                best, best_xy = m, (x, y)

    # map coords -> original pixels, then snap to exact aspect
    fx = img.width / mw
    fy = img.height / mh
    x0 = int(best_xy[0] * fx)
    y0 = int(best_xy[1] * fy)
    w = int(ww * fx)
    h = int(wh * fy)
    # enforce exact aspect within bounds (aspect drift from rounding)
    if w / h > aspect:
        w = int(h * aspect)
    else:
        h = int(w / aspect)
    x0 = min(max(0, x0), img.width - w)
    y0 = min(max(0, y0), img.height - h)
    return (x0, y0, w, h)


def adaptation_plan(width, height, style):
    """How to fit (width x height) media into 1080x1920 without stretching.

    Returns {"strategy": ..., "reason": ...}; strategies:
    - "portrait_crop": already portrait — direct subject crop/cover
    - "subject_crop": enough resolution to crop a 9:16 window out
    - "layered_frame": Archive-style framed object on the paper artboard
    - "blur_fill": original framing over a blurred self background
    """
    if height >= width:
        return {"strategy": "portrait_crop",
                "reason": f"portrait/square source ({width}x{height}) — cover crop"}
    crop_ok = height * UPSCALE_TOLERANCE >= MIN_CROP_HEIGHT
    if style == "archiveCollage":
        # the artboard uses framed photos by design; keep landscape framing
        return {"strategy": "layered_frame",
                "reason": "Archive presents photos as framed objects"}
    if crop_ok:
        return {"strategy": "subject_crop",
                "reason": f"can crop 9:16 at {height}px height without enlargement"}
    return {"strategy": "blur_fill",
            "reason": f"only {height}px tall — cropping would upscale beyond "
                      f"{UPSCALE_TOLERANCE}x, so keep framing over blurred fill"}
