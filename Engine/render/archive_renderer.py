"""Archive Collage final renderer (Phase 5).

Renders a scene plan (Phase 4) + fetched licensed media into the final
1080x1920/30fps video: warm paper artboard with intentional negative space,
monochrome archival photos as framed movable objects, translucent grey/black/
white blocks, slow editorial motion driven by the plan (beats only pulse),
plan-selected transitions, grain/vignette/dust, and EN+TR lyric strips on
irregular cream paper cutouts placed away from the photo.

`scene_layout` is pure and deterministic so composition rules (photo size
55–90% width, rotation ≤1.5°, consecutive-scene variety) are unit-testable
without rendering a single frame.
"""

import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proto_common import (FPS, H, W, VideoWriter, drop_shadow, ease_in_out,
                          lerp, make_grain_frames, mono_archive, paper_canvas,
                          vignette_map)
from subtitles.layout import Rect, place_block
from subtitles.render import build_archive_subtitle

OVERSIZE = 1.12          # artboard is rendered larger than the frame for drift

# style variants that reuse this renderer with a different visual language
VARIANTS = {
    "archiveCollage": {"canvas": (250, 249, 247), "rot": 0.35,
                       "border": "even", "sub_bg": (235, 224, 200),
                       "sub_ink": (58, 55, 50), "grade": "soft"},
    "polaroidWall":   {"canvas": (188, 154, 110), "rot": 3.5,
                       "border": "polaroid", "sub_bg": (250, 248, 242),
                       "sub_ink": (60, 56, 50), "grade": "soft"},
    "minimalDark":    {"canvas": (16, 16, 20), "rot": 0.0,
                       "border": "none", "sub_bg": (28, 28, 34),
                       "sub_ink": (238, 236, 230), "grade": "dark"},
}
_V = VARIANTS["archiveCollage"]   # active variant; render_archive swaps it
BLOCK_PALETTE = [        # translucent layered rectangles (grey/black/white)
    ((120, 118, 114), 200),
    ((60, 58, 56), 225),
    ((200, 197, 192), 170),
    ((240, 238, 233), 150),
    ((40, 38, 36), 240),
]
# position banks cycled so consecutive scenes never sit in the same corner
_PHOTO_ANCHORS = [(0.07, 0.15), (0.34, 0.10), (0.12, 0.24), (0.28, 0.18),
                  (0.05, 0.09), (0.20, 0.28)]


# ---------------------------------------------------------------------------
# Pure layout
# ---------------------------------------------------------------------------

def scene_layout(scene, index):
    """Deterministic composition spec for one scene.

    Returns dict with photo fraction geometry (of the oversized artboard),
    rotation, translucent blocks, zoom span and drift derived from the plan's
    motion, all within the style guide's ranges.
    """
    rng = random.Random(index * 977 + 13)
    motion = scene.get("motion", {})
    amount = float(motion.get("amount", 0.05))
    mtype = motion.get("type", "slow_push")

    # refs: centered artwork; alternate full-ish and small-panel scenes
    if index % 2 == 0:
        photo_w = 0.86 + 0.06 * rng.random()
    else:
        photo_w = 0.48 + 0.10 * rng.random()
    photo_pos = ((OVERSIZE - photo_w) / 2 + rng.uniform(-0.012, 0.012),
                 (0.20 if index % 2 == 0 else 0.30) + rng.uniform(-0.02, 0.02))
    rotation = rng.uniform(-_V["rot"], _V["rot"]) if _V["rot"] else 0.0

    n_blocks = 1 if index % 3 == 1 else 0              # blocks are rare now
    blocks = []
    for b in range(n_blocks):
        color, alpha = BLOCK_PALETTE[(index * 2 + b + 1) % len(BLOCK_PALETTE)]
        blocks.append({
            "pos": (rng.uniform(0.05, 0.62), rng.uniform(0.08, 0.72)),
            "size": (rng.uniform(0.18, 0.32), rng.uniform(0.14, 0.30)),
            "color": color,
            "alpha": min(alpha, 70),
            "in_front": b == 1 and index % 4 == 3,     # occasional front layer
            "drift": (rng.uniform(-14, 14), rng.uniform(-10, 10)),
        })

    zoom_span = 1.0 + amount * 0.8                     # slow push/pull scale
    if mtype == "slow_pull":
        zoom = (zoom_span, 1.0)
    elif mtype in ("slow_push", "layer_reposition"):
        zoom = (1.0, zoom_span)
    else:                                              # gentle_drift / rotate
        zoom = (1.0, 1.0 + amount * 0.3)
    drift_mag = 26 + amount * 300
    angle = rng.uniform(0, 6.283)
    drift = ((0.0, 0.0),
             (drift_mag * np.cos(angle), drift_mag * 0.6 * np.sin(angle)))

    # rhythm-aware density: calm lines hold one long image (uzun hava),
    # lively lines stack extra smaller frames around the main one
    band = scene.get("energy_band", "normal")
    extras = []
    # 1-3 images per scene, randomly (seeded): count = 1 + extras(0-2)
    count = rng.randint(0, 2)
    if count:
        spots = [((0.62, 0.10), 0.30), ((0.06, 0.58), 0.36),
                 ((0.64, 0.55), 0.28)]
        for k in range(count):
            (ex, ey), ew = spots[(index + k) % len(spots)]
            extras.append({"pos": (ex + rng.uniform(-0.02, 0.02),
                                   ey + rng.uniform(-0.02, 0.02)),
                           "w": ew + rng.uniform(-0.03, 0.04),
                           "rotation": rng.uniform(-1.2, 1.2)})

    return {
        "photo_w": photo_w if not extras else min(photo_w, 0.72),
        "photo_pos": photo_pos,
        "rotation": rotation,
        "blocks": blocks,
        "extras": extras,
        "zoom": zoom,
        "drift": drift,
        "max_photo_h": 0.60,                           # of artboard height
    }


def photo_screen_rect(layout):
    """Approximate on-screen Rect of the framed photo, assuming the
    centered crop at zoom≈1."""
    off = (OVERSIZE - 1.0) / 2.0
    x = (layout["photo_pos"][0] - off) * W * OVERSIZE
    y = (layout["photo_pos"][1] - off) * H * OVERSIZE
    w = layout["photo_w"] * W * OVERSIZE
    h = min(layout["max_photo_h"], layout["photo_w"] * 1.4) * H * OVERSIZE
    return Rect(max(0.0, x), max(0.0, y), w, h)


def subtitle_avoid_rect(layout):
    """Region subtitles must not cover: the upper part of the photo, where
    faces and focal subjects live. Strips may lap over the photo's bottom
    edge (editorial collage look) but never over faces."""
    rect = photo_screen_rect(layout)
    return Rect(rect.x, rect.y, rect.w, rect.h * 0.62)


def soft_archive_color(img):
    """Color archival grade: muted saturation, lifted blacks, softened
    contrast, faint warmth — analog and editorial but no forced monochrome."""
    from PIL import ImageEnhance
    img = ImageEnhance.Color(img).enhance(0.68)
    img = ImageEnhance.Contrast(img).enhance(0.90)
    arr = np.asarray(img, dtype=np.float32)
    arr = arr * 0.88 + 22.0                       # lift blacks, soften whites
    arr[..., 0] *= 1.03                           # faint warm cast
    arr[..., 2] *= 0.97
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------
# Layer building
# ---------------------------------------------------------------------------

def _load_scene_photo(scene):
    media = scene.get("media")
    if not media or not media.get("file_path"):
        return None
    path = Path(media["file_path"])
    if not path.exists():
        return None
    return Image.open(path).convert("RGB")


def build_scene_layer(scene, layout, seed, pool=()):
    """Oversized artboard: paper + blocks + framed monochrome photo."""
    bw, bh = int(W * OVERSIZE), int(H * OVERSIZE)
    board = Image.fromarray(paper_canvas(color=_V["canvas"],
                                         seed=7 + seed)).resize(
        (bw, bh), Image.BILINEAR)

    front_blocks = []
    for blk in layout["blocks"]:
        bx, by = int(bw * blk["pos"][0]), int(bh * blk["pos"][1])
        bw_, bh_ = int(bw * blk["size"][0]), int(bh * blk["size"][1])
        block = Image.new("RGBA", (bw_, bh_), (*blk["color"], blk["alpha"]))
        if blk["in_front"]:
            front_blocks.append((block, (bx, by)))
        else:
            board.paste(block, (bx, by), block)

    photo = _load_scene_photo(scene)
    if photo is not None:
        if _V["grade"] == "dark":
            from PIL import ImageEnhance
            photo = ImageEnhance.Contrast(
                ImageEnhance.Color(photo).enhance(0.85)).enhance(1.05)
        else:
            photo = soft_archive_color(photo)
        pw = int(bw * layout["photo_w"])
        ph = min(int(pw * photo.height / photo.width),
                 int(bh * layout["max_photo_h"]))
        from proto_common import cover_resize
        photo = cover_resize(photo, pw, ph)

        # frame treatment per variant
        if _V["border"] == "polaroid":
            border = max(14, pw // 40)
            framed = Image.new("RGB", (pw + border * 2,
                                       ph + border * 2 + border * 4),
                               (250, 249, 245))
            framed.paste(photo, (border, border))
        elif _V["border"] == "none":
            framed = photo
        else:
            border = max(10, pw // 60)
            framed = Image.new("RGB", (pw + border * 2, ph + border * 2),
                               (246, 244, 239))
            framed.paste(photo, (border, border))

        rotated = framed.convert("RGBA").rotate(
            layout["rotation"], expand=True, resample=Image.BICUBIC,
            fillcolor=(0, 0, 0, 0))
        px = int(bw * layout["photo_pos"][0])
        py = int(bh * layout["photo_pos"][1])
        shadow, pad, off = drop_shadow(rotated.size)
        board.paste(shadow, (px - pad + off[0], py - pad + off[1]), shadow)
        board.paste(rotated, (px, py), rotated)

    # extra smaller frames borrowed from neighbouring scenes' photos
    from proto_common import cover_resize as _cr
    for k, extra in enumerate(layout.get("extras", [])):
        if k >= len(pool):
            break
        try:
            img = Image.open(pool[k]).convert("RGB")
        except Exception:
            continue
        img = soft_archive_color(img)
        ew = int(bw * extra["w"])
        eh = min(int(ew * img.height / img.width), int(bh * 0.34))
        img = _cr(img, ew, eh)
        b2 = max(8, ew // 60)
        framed2 = Image.new("RGB", (ew + b2 * 2, eh + b2 * 2),
                            (246, 244, 239))
        framed2.paste(img, (b2, b2))
        rot2 = framed2.convert("RGBA").rotate(extra["rotation"], expand=True,
                                              resample=Image.BICUBIC,
                                              fillcolor=(0, 0, 0, 0))
        ex, ey = int(bw * extra["pos"][0]), int(bh * extra["pos"][1])
        sh2, pad2, off2 = drop_shadow(rot2.size)
        board.paste(sh2, (ex - pad2 + off2[0], ey - pad2 + off2[1]), sh2)
        board.paste(rot2, (ex, ey), rot2)

    for block, pos in front_blocks:
        board.paste(block, pos, block)
    return board


def _fade_alpha(img, alpha):
    if alpha >= 1.0:
        return img
    faded = img.copy()
    faded.putalpha(faded.getchannel("A").point(lambda v: int(v * alpha)))
    return faded


# ---------------------------------------------------------------------------
# Frame sampling
# ---------------------------------------------------------------------------

def _beat_pulse(t, pulse_beats, strength=0.009, decay=0.16):
    pulse = 0.0
    for b in pulse_beats:
        dt = t - b
        if 0.0 <= dt < decay:
            pulse = max(pulse, strength * (1.0 - dt / decay))
    return pulse


def _scene_frame(layer, layout, local, scene_len, t_local, pulse_beats):
    """Crop the oversized layer for one frame (zoom + drift + beat pulse)."""
    e = ease_in_out(min(1.0, local))
    z = lerp(layout["zoom"][0], layout["zoom"][1], e)
    z *= 1.0 + _beat_pulse(t_local, pulse_beats)
    dx = lerp(layout["drift"][0][0], layout["drift"][1][0], e)
    dy = lerp(layout["drift"][0][1], layout["drift"][1][1], e)

    lw, lh = layer.size
    cw, ch = int(W / z), int(H / z)
    cx = max(0, min(lw - cw, (lw - cw) / 2 + dx))
    cy = max(0, min(lh - ch, (lh - ch) / 2 + dy))
    frame = layer.crop((int(cx), int(cy), int(cx) + cw, int(cy) + ch))
    if (cw, ch) != (W, H):
        frame = frame.resize((W, H), Image.BILINEAR)
    return np.asarray(frame.convert("RGB"), dtype=np.float32)


def _apply_transition(arr, prev_arr, kind, progress):
    """Blend into the incoming scene during its transition window."""
    p = ease_in_out(progress)
    if kind == "fade_white":
        if p < 0.5:
            return prev_arr * (1 - p * 2 * 0.92) + 248.0 * (p * 2 * 0.92)
        q = (p - 0.5) * 2
        return arr * (1 - (1 - q) * 0.92) + 248.0 * ((1 - q) * 0.92)
    if kind == "fade_dark":
        if p < 0.5:
            return prev_arr * (1 - p * 2 * 0.94) + 16.0 * (p * 2 * 0.94)
        q = (p - 0.5) * 2
        return arr * (1 - (1 - q) * 0.94) + 16.0 * ((1 - q) * 0.94)
    if kind == "block_wipe":
        edge = int(H * p)
        out = prev_arr.copy()
        out[:edge] = arr[:edge]
        band = slice(max(0, edge - 14), edge)
        out[band] = out[band] * 0.4 + 235.0 * 0.6   # paper edge on the wipe
        return out
    # crossfade / layered_dissolve
    return prev_arr * (1 - p) + arr * p


def _dust_layer(shape, rng):
    """Sparse dust specks + one scratch line, regenerated every few frames."""
    dust = np.zeros(shape[:2], dtype=np.float32)
    for _ in range(rng.integers(4, 10)):
        y, x = rng.integers(0, shape[0]), rng.integers(0, shape[1])
        dust[y:y + 2, x:x + 2] = rng.uniform(20, 60)
    if rng.random() < 0.5:
        x = rng.integers(0, shape[1])
        y0 = rng.integers(0, shape[0] - 240)
        dust[y0:y0 + rng.integers(90, 240), x] = rng.uniform(14, 34)
    return dust[..., None]


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_archive(plan, audio_path, out_path, progress=None):
    global _V
    _V = VARIANTS.get(plan.get("style"), VARIANTS["archiveCollage"])
    """Render the full Archive Collage video for a media-annotated plan.

    Returns the list of QA frame paths written next to the video.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    seg_start = float(plan["segment_start"])
    duration = float(plan["segment_end"]) - seg_start

    layouts = [scene_layout(s, i) for i, s in enumerate(scenes)]
    def pool_for(i):
        # strictly the scene's OWN pool: an image shown in one scene must
        # never appear again in another
        return list(scenes[i].get("extra_media") or [])

    layers = [build_scene_layer(s, l, i, pool_for(i))
              for i, (s, l) in enumerate(zip(scenes, layouts))]

    # rhythm-driven image swaps: energetic lines cycle neighbouring photos
    # behind the lyric on the beat (reference-video behaviour)
    # swap cadence follows the song: one hit per beat period, driven by
    # percussive onsets (bass/drums) when available
    tempo = float(plan.get("tempo_bpm") or 100.0)
    beat_period = max(0.45, min(1.4, 60.0 / max(40.0, tempo)))
    variant_layers = []
    swap_beats = []
    for i, scene in enumerate(scenes):
        variants = [layers[i]]
        beats = []
        band = scene.get("energy_band", "normal")
        own_pool = pool_for(i)
        if band != "calm" and own_pool:
            main = (scene.get("media") or {}).get("file_path")
            trio = [q for q in [main] + own_pool if q][:3]
            # rotate roles: every variant shows the SAME images, only the
            # large frame changes - swaps stay visually coherent
            for r in range(1, len(trio)):
                rotated = trio[r:] + trio[:r]
                variants.append(build_scene_layer(
                    {"media": {"file_path": rotated[0]}}, layouts[i], i,
                    rotated[1:]))
            # cadence: every beat when energetic, every 2nd beat when normal
            gap = beat_period * (2.0 if band == "energetic" else 4.0)
            hits = (scene.get("motion", {}).get("onsets")
                    or scene.get("motion", {}).get("pulse_beats", []))
            scene_len = max(0.001, scene["end"] - scene["start"])
            last = -10.0
            for b in hits:
                if b < 1.1 or b > scene_len - 0.7:
                    continue          # let the sentence settle / leave calmly
                if b - last >= gap:
                    beats.append(b)
                    last = b
        variant_layers.append(variants)
        swap_beats.append(beats)

    # subtitles: one block per lyric scene, placed away from the photo
    subtitles = []
    for i, scene in enumerate(scenes):
        if not scene.get("lyric"):
            subtitles.append(None)
            continue
        block, size = build_archive_subtitle(
            scene["lyric"], scene.get("translation"), seed=i,
            uncertain=bool(scene.get("uncertain")),
            bg=_V["sub_bg"], ink=_V["sub_ink"])
        if block is None:
            subtitles.append(None)
            continue
        band = (scene.get("subtitle") or {}).get("band", "lower")
        rect = place_block(size, avoid=[subtitle_avoid_rect(layouts[i])],
                           preferred=band, seed=i)
        subtitles.append((block, rect))

    grain = make_grain_frames(strength=4.5)
    vig = vignette_map(0.16)
    total = int(round(duration * FPS))
    rng = np.random.default_rng(4242)
    flicker = 1.0 + np.cumsum(rng.normal(0, 0.004, total)).clip(-0.02, 0.02)
    dust_rng = np.random.default_rng(777)
    dust = None

    writer = VideoWriter(out_path, audio_path, audio_offset=seg_start,
                         duration=duration)
    qa_at = sorted({min(total - 1, int(total * f))
                    for f in (0.06, 0.28, 0.5, 0.72, 0.94)})
    qa_paths = []
    try:
        for n in range(total):
            t = n / FPS
            idx = len(scenes) - 1
            for i, s in enumerate(scenes):
                if s["start"] <= t < s["end"]:
                    idx = i
                    break
            scene, layout = scenes[idx], layouts[idx]
            scene_len = max(0.001, scene["end"] - scene["start"])
            t_local = t - scene["start"]
            local = t_local / scene_len
            pulses = scene.get("motion", {}).get("pulse_beats", [])

            variants = variant_layers[idx]
            layer = variants[0]
            blend_prev, blend_p = None, 1.0
            if len(variants) > 1 and swap_beats[idx]:
                hits = [b for b in swap_beats[idx] if b <= t_local]
                passed = len(hits)
                layer = variants[passed % len(variants)]
                if hits:
                    since = t_local - hits[-1]
                    if since < 0.3:            # swaps melt, never snap
                        blend_prev = variants[(passed - 1) % len(variants)]
                        blend_p = ease_in_out(since / 0.3)
            arr = _scene_frame(layer, layout, local, scene_len,
                               t_local, pulses)
            if blend_prev is not None:
                prev_arr = _scene_frame(blend_prev, layout, local,
                                        scene_len, t_local, pulses)
                arr = prev_arr * (1 - blend_p) + arr * blend_p

            # sentence changes are clean cuts: the new photo count and
            # placement IS the transition (user direction, and cheaper)
            # subtitle strip (enter 0.35s after transition, exit 0.25s)
            if subtitles[idx] is not None:
                block, rect = subtitles[idx]
                enter = min(1.0, max(0.0, t_local / 0.6))
                exit_ = min(1.0, (scene["end"] - t) / 0.7)
                alpha = ease_in_out(max(0.0, min(enter, exit_)))
                if alpha > 0.01:
                    rise = (1.0 - ease_in_out(enter)) * 20
                    faded = _fade_alpha(block, alpha)
                    tmp = Image.fromarray(arr.astype(np.uint8))
                    tmp.paste(faded, (int(rect.x), int(rect.y + rise)), faded)
                    arr = np.asarray(tmp, dtype=np.float32)

            # grade: flicker + vignette + grain (+ dust on flagged scenes)
            arr *= flicker[n] * vig
            arr += grain[n % len(grain)]
            if "dust_flicker" in (scene.get("overlays") or []):
                if dust is None or n % 5 == 0:
                    dust = _dust_layer(arr.shape, dust_rng)
                arr += dust

            writer.write(np.clip(arr, 0, 255).astype(np.uint8))
            if n in qa_at:
                qa = out_path.with_name(f"{out_path.stem}_qa_{n:04d}.png")
                Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(qa)
                qa_paths.append(str(qa))
            if progress and n % 30 == 0:
                progress(n / total,
                         f"Rendering Archive Collage… {int(100 * n / total)}%")
    finally:
        writer.close()
    return qa_paths
