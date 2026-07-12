"""Shared helpers for the Phase 0 prototype renders.

Everything is deterministic: all randomness goes through seeded RNGs so a
re-render produces the identical video.
"""

import math
import os
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1080, 1920, 30

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = REPO_ROOT / "References" / "proto_media"
OUTPUT_DIR = REPO_ROOT / "Output" / "prototypes"

FONT_TYPEWRITER = "/System/Library/Fonts/Supplemental/AmericanTypewriter.ttc"
FONT_HAND = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"


def find_tool(name):
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which(name)


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


def ease_in_out(t):
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Canvas, grain, grade
# ---------------------------------------------------------------------------

def paper_canvas(color=(242, 240, 236), seed=7):
    """Warm off-white paper with faint speckle so it doesn't look digital."""
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), color, dtype=np.float32)
    speckle = rng.normal(0.0, 2.2, size=(H, W, 1)).astype(np.float32)
    base = np.clip(base + speckle, 0, 255)
    return base.astype(np.uint8)


def make_grain_frames(count=8, strength=5.0, seed=99):
    """Pre-generated film-grain deltas cycled over time (int16, HxWx1)."""
    rng = np.random.default_rng(seed)
    return [rng.normal(0.0, strength, size=(H, W, 1)).astype(np.int16)
            for _ in range(count)]


def vignette_map(strength=0.18):
    """Multiplicative vignette (float32 HxWx1, 1.0 center, darker corners)."""
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xs - W / 2) / (W / 2)
    ny = (ys - H / 2) / (H / 2)
    r2 = nx * nx + ny * ny
    return (1.0 - strength * np.clip(r2 - 0.25, 0, 1.5) / 1.5)[..., None]


def warm_memory_lut():
    """Luminance -> warm nostalgic duotone (amber highlights, olive shadows)."""
    stops = [
        (0.00, (40, 36, 22)),
        (0.35, (101, 84, 48)),
        (0.65, (188, 148, 84)),
        (0.85, (232, 203, 138)),
        (1.00, (247, 233, 186)),
    ]
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                lut[i] = [round(lerp(c0[k], c1[k], f)) for k in range(3)]
                break
    return lut


def apply_lut(gray_u8, lut):
    return lut[gray_u8]


def posterize_levels(arr_u8, levels=7):
    step = 255.0 / (levels - 1)
    return (np.round(arr_u8.astype(np.float32) / step) * step).clip(0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

def load_photo(slug, crop_frac=None):
    """Load a prototype photo; crop_frac=(l, t, r, b) trims scan borders."""
    img = Image.open(MEDIA_DIR / f"{slug}.jpg").convert("RGB")
    if crop_frac:
        l, t, r, b = crop_frac
        w, h = img.size
        img = img.crop((int(w * l), int(h * t), int(w * r), int(h * b)))
    return img


def mono_archive(img, lift=26, gain=0.84):
    """Monochrome archival grade: softened contrast, lifted blacks."""
    g = np.asarray(ImageOps.autocontrast(img.convert("L"), cutoff=1),
                   dtype=np.float32)
    g = np.clip(g * gain + lift, 0, 255).astype(np.uint8)
    return Image.fromarray(g).convert("RGB")


def cover_resize(img, tw, th):
    """Resize + center-crop to exactly (tw, th)."""
    return ImageOps.fit(img, (tw, th), Image.LANCZOS)


def drop_shadow(size, radius=18, alpha=90, offset=(10, 16)):
    """RGBA shadow layer a bit larger than `size`."""
    w, h = size
    pad = radius * 3
    layer = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    draw = ImageDraw.Draw(layer)
    draw.rectangle((pad, pad, pad + w, pad + h), fill=alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    rgba = Image.new("RGBA", layer.size, (20, 18, 16, 0))
    rgba.putalpha(layer)
    return rgba, pad, offset


# ---------------------------------------------------------------------------
# Irregular paper stickers / tape labels
# ---------------------------------------------------------------------------

def _jitter_outline(box, rng, jitter=5, seg=26):
    """Closed polygon roughly following `box` with hand-cut jitter."""
    x0, y0, x1, y1 = box
    pts = []
    def edge(ax, ay, bx, by):
        n = max(2, int(math.hypot(bx - ax, by - ay) / seg))
        for i in range(n):
            t = i / n
            pts.append((lerp(ax, bx, t) + rng.uniform(-jitter, jitter),
                        lerp(ay, by, t) + rng.uniform(-jitter, jitter)))
    edge(x0, y0, x1, y0)
    edge(x1, y0, x1, y1)
    edge(x1, y1, x0, y1)
    edge(x0, y1, x0, y0)
    return pts


def paper_sticker(text, font_path, font_size, text_fill=(58, 55, 50),
                  bg=(238, 228, 202), border=None, pad=(26, 14),
                  rotation=0.0, seed=1, jitter=5):
    """Text on an irregular paper cutout. Returns RGBA image."""
    rng = random.Random(seed)
    font = ImageFont.truetype(font_path, font_size)
    probe = Image.new("RGBA", (8, 8))
    tb = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    m = jitter * 3
    img = Image.new("RGBA", (tw + pad[0] * 2 + m * 2, th + pad[1] * 2 + m * 2),
                    (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    box = (m, m, m + tw + pad[0] * 2, m + th + pad[1] * 2)
    pts = _jitter_outline(box, rng, jitter=jitter)
    if border:
        draw.polygon(pts, fill=bg, outline=border[0], width=border[1])
    else:
        draw.polygon(pts, fill=bg)
    draw.text((m + pad[0] - tb[0], m + pad[1] - tb[1]), text,
              font=font, fill=text_fill)
    if rotation:
        img = img.rotate(rotation, expand=True, resample=Image.BICUBIC)
    return img


def alpha_paste(base_arr, overlay, xy):
    """Paste RGBA overlay onto uint8 RGB numpy array in place."""
    x, y = int(xy[0]), int(xy[1])
    ow, oh = overlay.size
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + ow, W), min(y + oh, H)
    if x0 >= x1 or y0 >= y1:
        return
    ov = np.asarray(overlay, dtype=np.float32)[y0 - y:y1 - y, x0 - x:x1 - x]
    a = ov[..., 3:4] / 255.0
    region = base_arr[y0:y1, x0:x1].astype(np.float32)
    base_arr[y0:y1, x0:x1] = (region * (1 - a) + ov[..., :3] * a).astype(np.uint8)


# ---------------------------------------------------------------------------
# Video writer (rawvideo pipe -> ffmpeg, audio muxed from licensed source)
# ---------------------------------------------------------------------------

class VideoWriter:
    def __init__(self, out_path, audio_path, audio_offset=0.0, duration=15.0):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fade_out = max(duration - 0.6, 0)
        cmd = [
            FFMPEG, "-y", "-nostdin", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
            "-r", str(FPS), "-i", "-",
            "-ss", str(audio_offset), "-t", str(duration), "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            "-af", f"afade=t=in:d=0.6,afade=t=out:st={fade_out}:d=0.6",
            "-shortest", str(out_path),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame_u8):
        self.proc.stdin.write(frame_u8.tobytes())

    def close(self):
        self.proc.stdin.close()
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited with {rc}")


def find_job_audio():
    """First ingested audio file from the Step 2 pipeline (licensed source)."""
    for p in sorted((REPO_ROOT / "Cache" / "jobs").glob("*/audio.m4a")):
        return p
    raise FileNotFoundError("No Cache/jobs/*/audio.m4a — run an ingestion job first.")
