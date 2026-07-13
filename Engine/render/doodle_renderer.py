"""Doodle Memory final renderer (Phase 6).

Full-frame warm nostalgic imagery from the fetched media (subject-aware
adaptation, never stretched), curated transparent doodles that sit in the
environment (ground-anchored figures on the lower third, sky elements up
top), word-timed handwritten navy stickers, phrase cuts / paper wipes /
sticker pops, subtle breathing motion and beat micro-bounces.

`doodle_layout` is pure so placement rules are unit-testable.
"""

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from doodle_library import build_doodle, is_ground_anchored, pick_doodle
from media.crop import subject_crop
from proto_common import (FPS, H, W, VideoWriter, apply_lut, cover_resize,
                          ease_in_out, make_grain_frames, posterize_levels,
                          vignette_map, warm_memory_lut)
from subtitles.layout import SAFE_ZONE, Rect, place_block
from subtitles.render import build_doodle_translation, build_doodle_words

OVERSIZE = 1.08


# ---------------------------------------------------------------------------
# Pure layout
# ---------------------------------------------------------------------------

def doodle_layout(scene_index, name, ground_anchored):
    """Deterministic doodle placement (fractions of the 1080x1920 frame).

    Ground-anchored doodles stand on the lower third (feet around 84–90 %
    height); sky/ambient doodles float in the upper part. Horizontal side
    alternates per scene so consecutive scenes vary.
    """
    rng = random.Random(scene_index * 613 + hash(name) % 1000)
    side = -1 if scene_index % 2 == 0 else 1
    if ground_anchored:
        height_frac = 0.30 + 0.08 * rng.random()
        bottom_frac = 0.845 + 0.05 * rng.random()
        x_center = 0.5 + side * (0.16 + 0.10 * rng.random())
        return {"height_frac": height_frac, "bottom_frac": bottom_frac,
                "x_center": min(0.80, max(0.20, x_center)), "side": side}
    height_frac = 0.16 + 0.08 * rng.random()
    bottom_frac = 0.22 + 0.16 * rng.random()
    x_center = 0.5 + side * (0.20 + 0.08 * rng.random())
    return {"height_frac": height_frac, "bottom_frac": bottom_frac,
            "x_center": min(0.82, max(0.18, x_center)), "side": side}


def doodle_screen_rect(layout, aspect):
    """On-screen Rect of the doodle for subtitle collision avoidance."""
    h = layout["height_frac"] * H
    w = h * aspect
    x = layout["x_center"] * W - w / 2
    y = layout["bottom_frac"] * H - h
    return Rect(x, y, w, h)


# ---------------------------------------------------------------------------
# Background building
# ---------------------------------------------------------------------------

def _warm_gradient(seed=11):
    ys = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    top = np.array([236, 205, 140], dtype=np.float32)
    bottom = np.array([116, 112, 78], dtype=np.float32)
    base = np.broadcast_to(top * (1 - ys) + bottom * ys, (H, W, 3)).copy()
    rng = np.random.default_rng(seed)
    base += rng.normal(0.0, 2.0, size=(H, W, 1)).astype(np.float32)
    return np.clip(base, 0, 255).astype(np.uint8)


def _adapted_full_frame(img, strategy, ow, oh):
    """Fit media into (ow, oh) per the plan's adaptation — never stretch."""
    if strategy == "subject_crop":
        x, y, w, h = subject_crop(img, aspect=ow / oh)
        return img.crop((x, y, x + w, y + h)).resize((ow, oh), Image.LANCZOS)
    if strategy == "blur_fill":
        bg = cover_resize(img, ow, oh).filter(ImageFilter.GaussianBlur(28))
        scale = min(ow / img.width, oh / img.height)
        fw, fh = int(img.width * scale), int(img.height * scale)
        fg = img.resize((fw, fh), Image.LANCZOS)
        bg.paste(fg, ((ow - fw) // 2, (oh - fh) // 2))
        return bg
    return cover_resize(img, ow, oh)          # portrait/square cover crop


def build_scene_background(scene, lut):
    """Oversized warm-graded background layer for one scene."""
    bw, bh = int(W * OVERSIZE), int(H * OVERSIZE)
    media = scene.get("media")
    img = None
    if media and media.get("file_path") and Path(media["file_path"]).exists():
        img = Image.open(media["file_path"]).convert("RGB")
    if img is None:
        return Image.fromarray(_warm_gradient()).resize((bw, bh),
                                                        Image.BILINEAR)
    strategy = (media.get("adaptation") or {}).get("strategy", "portrait_crop")
    frame = _adapted_full_frame(img, strategy, bw, bh)

    # lively, colorful grade: boosted saturation and brightness with only a
    # whisper of warmth — Doodle Memory is the cheerful, playful style
    from PIL import ImageEnhance
    frame = ImageEnhance.Color(frame).enhance(1.35)
    frame = ImageEnhance.Brightness(frame).enhance(1.06)
    frame = ImageEnhance.Contrast(frame).enhance(1.08)
    gray = np.asarray(frame.convert("L"))
    warm = apply_lut(posterize_levels(gray, levels=24), lut).astype(np.float32)
    color = np.asarray(frame, dtype=np.float32)
    blended = np.clip(color * 0.85 + warm * 0.15, 0, 255).astype(np.uint8)
    return Image.fromarray(blended)


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def _fade_alpha(img, alpha):
    if alpha >= 1.0:
        return img
    faded = img.copy()
    faded.putalpha(faded.getchannel("A").point(lambda v: int(v * alpha)))
    return faded


def _bounce(t, pulse_beats, amp=9.0, decay=0.18):
    for b in pulse_beats:
        dt = t - b
        if 0.0 <= dt < decay:
            return amp * math.sin(math.pi * dt / decay)
    return 0.0


def render_doodle(plan, words_by_line, audio_path, out_path, progress=None):
    """Render the Doodle Memory video for a media-annotated plan.

    `words_by_line`: {line_index: [{"text","start","end"}]} with times
    relative to the segment (for word-timed sticker pops). Returns QA frame
    paths.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    seg_start = float(plan["segment_start"])
    duration = float(plan["segment_end"]) - seg_start

    lut = warm_memory_lut()
    backgrounds = [build_scene_background(s, lut) for s in scenes]

    prepared = []      # per scene: doodle sprite + layout + subtitle stickers
    for i, scene in enumerate(scenes):
        name = pick_doodle(scene.get("subjects"), i)
        layout = doodle_layout(i, name, is_ground_anchored(name))
        sprite = build_doodle(name, height=int(layout["height_frac"] * H))
        d_rect = doodle_screen_rect(layout, sprite.width / sprite.height)

        stickers = None
        translation = None
        if scene.get("lyric"):
            words = words_by_line.get(scene.get("line_index"), [])
            items, size = build_doodle_words(
                [w["text"] for w in words] or scene["lyric"].split(),
                seed=i, uncertain=bool(scene.get("uncertain")))
            if items:
                band = (scene.get("subtitle") or {}).get("band", "lower")
                tr_block = build_doodle_translation(scene.get("translation"),
                                                    seed=i)
                tr_h = (tr_block.height + 10) if tr_block else 0
                s_rect = place_block((size[0], size[1] + tr_h),
                                     avoid=[d_rect], preferred=band, seed=i)
                word_times = [w.get("start") for w in words] if words else []
                stickers = (items, s_rect, word_times)
                if tr_block:
                    tr_x = s_rect.x + (s_rect.w - tr_block.width) / 2
                    tr_x = min(max(tr_x, SAFE_ZONE.x),
                               SAFE_ZONE.right - tr_block.width)
                    translation = (tr_block,
                                   (int(tr_x), int(s_rect.y + size[1] + 10)))
        prepared.append({"name": name, "sprite": sprite, "layout": layout,
                         "stickers": stickers, "translation": translation})

    grain = make_grain_frames(strength=4.0)
    vig = vignette_map(0.14)
    total = int(round(duration * FPS))
    qa_at = sorted({min(total - 1, int(total * f))
                    for f in (0.06, 0.28, 0.5, 0.72, 0.94)})
    qa_paths = []

    def compose(idx, t):
        """Full composed RGB frame (background + doodle + stickers) at t."""
        scene = scenes[idx]
        prep = prepared[idx]
        scene_len = max(0.001, scene["end"] - scene["start"])
        t_local = t - scene["start"]
        local = min(1.0, max(0.0, t_local / scene_len))
        pulses = scene.get("motion", {}).get("pulse_beats", [])

        bg = backgrounds[idx]
        z = 1.0 + 0.035 * ease_in_out(local)
        lw, lh = bg.size
        cw, ch = min(int(lw / z), lw), min(int(lh / z), lh)
        cx = (lw - cw) / 2
        cy = (lh - ch) * (0.5 - 0.06 * ease_in_out(local))
        frame = bg.crop((int(cx), int(cy), int(cx) + cw, int(cy) + ch))
        if (frame.width, frame.height) != (W, H):
            frame = frame.resize((W, H), Image.BILINEAR)

        # doodle: slide-in entrance, breathe, beat micro-bounce
        sprite, layout = prep["sprite"], prep["layout"]
        enter = ease_in_out(min(1.0, t_local / 0.3))
        breathe = 1.0 + 0.028 * math.sin(2 * math.pi * t_local / 1.8)
        dh = int(layout["height_frac"] * H * breathe)
        dw = int(dh * sprite.width / sprite.height)
        scaled = sprite.resize((max(1, dw), max(1, dh)), Image.BILINEAR)
        x = int(layout["x_center"] * W - dw / 2
                + (1 - enter) * layout["side"] * 90)
        y = int(layout["bottom_frac"] * H - dh
                + _bounce(t_local, pulses))
        frame.paste(_fade_alpha(scaled, enter), (x, y),
                    _fade_alpha(scaled, enter))

        # word stickers pop in at their aligned times
        if prep["stickers"]:
            items, s_rect, word_times = prep["stickers"]
            exit_ = min(1.0, max(0.0, (scene["end"] - t) / 0.2))
            for sticker, (dx, dy), wi in items:
                wt = word_times[wi] if wi < len(word_times) else None
                rel = None if wt is None else wt - scene["start"]
                if rel is not None and t_local < rel:
                    continue
                pop = 1.0 if rel is None else \
                    ease_in_out(min(1.0, max(0.0, (t_local - rel) / 0.14)))
                alpha = pop * exit_
                if alpha <= 0.01:
                    continue
                faded = _fade_alpha(sticker, alpha)
                frame.paste(faded,
                            (int(s_rect.x + dx),
                             int(s_rect.y + dy + (1 - pop) * 8)), faded)

        # Turkish translation strip under the original words
        if prep["translation"]:
            tr_block, (tx, ty) = prep["translation"]
            exit_ = min(1.0, max(0.0, (scene["end"] - t) / 0.2))
            tr_alpha = ease_in_out(min(1.0, t_local / 0.4)) * exit_
            if tr_alpha > 0.01:
                faded = _fade_alpha(tr_block, tr_alpha)
                frame.paste(faded, (tx, ty), faded)
        return np.asarray(frame, dtype=np.float32)

    writer = VideoWriter(out_path, audio_path, audio_offset=seg_start,
                         duration=duration)
    try:
        for n in range(total):
            t = n / FPS
            idx = len(scenes) - 1
            for i, s in enumerate(scenes):
                if s["start"] <= t < s["end"]:
                    idx = i
                    break
            arr = compose(idx, t)

            scene = scenes[idx]
            trans = scene.get("transition") or {}
            tdur = float(trans.get("duration") or 0)
            t_local = t - scene["start"]
            if idx > 0 and tdur > 0 and t_local < tdur:
                p = ease_in_out(t_local / tdur)
                prev_arr = compose(idx - 1, scenes[idx - 1]["end"] - 1e-3)
                kind = trans.get("type")
                if kind == "paper_wipe":
                    edge = int(W * p)
                    out = prev_arr.copy()
                    out[:, :edge] = arr[:, :edge]
                    band = slice(max(0, edge - 12), edge)
                    out[:, band] = out[:, band] * 0.35 + 246.0 * 0.65
                    arr = out
                elif kind == "sticker_pop":
                    arr = prev_arr * (1 - p) + arr * p
                    arr = np.clip(arr + (1 - p) * 26.0, 0, 255)  # pop flash
                else:                       # short_dissolve ("cut" has tdur 0)
                    arr = prev_arr * (1 - p) + arr * p

            arr *= vig
            arr += grain[n % len(grain)]
            frame_u8 = np.clip(arr, 0, 255).astype(np.uint8)
            writer.write(frame_u8)
            if n in qa_at:
                qa = out_path.with_name(f"{out_path.stem}_qa_{n:04d}.png")
                Image.fromarray(frame_u8).save(qa)
                qa_paths.append(str(qa))
            if progress and n % 30 == 0:
                progress(n / total,
                         f"Rendering Doodle Memory… {int(100 * n / total)}%")
    finally:
        writer.close()
    return qa_paths
