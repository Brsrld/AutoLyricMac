#!/usr/bin/env python3
"""Doodle Memory 15-second prototype (Phase 0).

Four lyric-phrase scenes: full-bleed warm-graded posterized photographs with
procedural doodle characters interacting with the real environment, hard
phrase cuts, handwritten Turkish lyric words on cream sticker blobs. Lyric:
"Üsküdar'a Gider İken" (traditional, public domain). Deterministic.
"""

import numpy as np
from PIL import Image

import doodles
from proto_common import (
    FONT_HAND, FPS, H, OUTPUT_DIR, VideoWriter, W, alpha_paste, cover_resize,
    find_job_audio, load_photo, make_grain_frames, paper_sticker,
    posterize_levels, vignette_map, warm_memory_lut, apply_lut,
)

DURATION = 15.0
CUTS = [0.0, 4.0, 8.0, 11.5, 15.0]  # scene boundaries (hard cuts)

LUT = warm_memory_lut()


def warm_background(slug, crop, zoom_center=(0.5, 0.5), zoom=1.0):
    """Full-bleed 1080x1920 warm posterized background from a photo."""
    img = load_photo(slug, crop)
    if zoom > 1.0:
        w, h = img.size
        cw, ch = int(w / zoom), int(h / zoom)
        cx = int((w - cw) * zoom_center[0])
        cy = int((h - ch) * zoom_center[1])
        img = img.crop((cx, cy, cx + cw, cy + ch))
    img = cover_resize(img, W, H)
    gray = np.asarray(img.convert("L"))
    warm = apply_lut(gray, LUT)
    return posterize_levels(warm, levels=8)


def word_stickers(words, seed0):
    """One handwritten sticker per word/word-group."""
    return [paper_sticker(word, FONT_HAND, 64, text_fill=(29, 42, 82),
                          bg=(240, 234, 211), border=((252, 250, 242), 6),
                          pad=(22, 12), rotation=rot, seed=seed0 + i, jitter=7)
            for i, (word, rot) in enumerate(words)]


def build_scenes():
    scenes = []

    # 1 — kitchen stove, mother at the stove, steam from the real kettle
    bg = warm_background("kitchen_window", (0.02, 0.02, 0.96, 0.97))
    scenes.append({
        "bg": bg,
        "doodles": [
            (doodles.standing_figure(height=820, seed=3), (150, 880), 0.012),
            (doodles.steam_squiggle(height=260, seed=9), (610, 300), 0.02),
        ],
        "words": word_stickers([("üsküdar'a", -3), ("gider", 2), ("iken", -1.5)],
                               seed0=100),
        "word_pos": [(90, 190), (470, 240), (700, 180)],
    })

    # 2 — same kitchen, closer crop: child sits by the stove, rain outside
    bg = warm_background("kitchen_window", (0.02, 0.02, 0.96, 0.97),
                         zoom_center=(0.75, 0.55), zoom=1.5)
    scenes.append({
        "bg": bg,
        "doodles": [
            (doodles.sitting_child(height=460, seed=11), (560, 1050), 0.015),
            (doodles.raindrops(size=420, seed=13), (90, 320), 0.02),
        ],
        "words": word_stickers([("aldı da", 2.5), ("bir", -2), ("yağmur", 1.5)],
                               seed0=200),
        "word_pos": [(120, 210), (520, 260), (680, 190)],
    })

    # 3 — bright room, mother by the window, sun outside the real window
    bg = warm_background("living_room", (0.035, 0.02, 0.89, 0.97))
    scenes.append({
        "bg": bg,
        "doodles": [
            (doodles.standing_figure(height=760, seed=17), (620, 950), 0.012),
            (doodles.sun(size=300, seed=5), (430, 620), 0.018),
        ],
        "words": word_stickers([("kâtibimin", -2), ("setresi", 1.5), ("uzun", -2.5)],
                               seed0=300),
        "word_pos": [(110, 200), (500, 250), (740, 185)],
    })

    # 4 — park path, hugging pair on the real path
    bg = warm_background("park_bench", (0.06, 0.14, 0.93, 0.96),
                         zoom_center=(0.3, 0.75), zoom=1.25)
    scenes.append({
        "bg": bg,
        "doodles": [
            (doodles.hugging_pair(height=680, seed=21), (110, 1050), 0.014),
        ],
        "words": word_stickers([("eteği", 2), ("çamur", -2)], seed0=400),
        "word_pos": [(160, 210), (560, 260)],
    })
    return scenes


def main():
    audio = find_job_audio()
    out = OUTPUT_DIR / "doodle_memory_proto.mp4"
    writer = VideoWriter(out, audio, audio_offset=470.0, duration=DURATION)

    scenes = build_scenes()
    grain = make_grain_frames(strength=6.0, seed=41)
    vig = vignette_map(0.12)
    total = int(DURATION * FPS)

    for f in range(total):
        t = f / FPS
        idx = next(i for i in range(len(CUTS) - 1)
                   if CUTS[i] <= t < CUTS[i + 1] or i == len(CUTS) - 2)
        scene = scenes[idx]
        local = t - CUTS[idx]

        arr = scene["bg"].copy()

        # doodles breathe 1-2% and sway very slightly
        for k, (img, (x, y), amp) in enumerate(scene["doodles"]):
            phase = 2 * np.pi * (local * 0.55 + k * 0.3)
            scale = 1.0 + amp * np.sin(phase)
            rot = 1.2 * np.sin(phase * 0.7 + k)
            dw = int(img.width * scale)
            dh = int(img.height * scale)
            frame_doodle = img.resize((dw, dh), Image.BILINEAR)
            if abs(rot) > 0.05:
                frame_doodle = frame_doodle.rotate(rot, expand=False,
                                                   resample=Image.BILINEAR)
            alpha_paste(arr, frame_doodle,
                        (x - (dw - img.width) // 2, y - (dh - img.height) // 2))

        # words pop in one after another (sticker pop ≈ 0.18 s each)
        for k, (sticker, (x, y)) in enumerate(zip(scene["words"],
                                                  scene["word_pos"])):
            start = 0.25 + k * 0.35
            if local < start:
                continue
            pop = min(1.0, (local - start) / 0.18)
            if pop < 1.0:
                s = 0.6 + 0.4 * pop
                pw, ph_ = int(sticker.width * s), int(sticker.height * s)
                small = sticker.resize((pw, ph_), Image.BILINEAR)
                alpha_paste(arr, small, (x + (sticker.width - pw) // 2,
                                         y + (sticker.height - ph_) // 2))
            else:
                alpha_paste(arr, sticker, (x, y))

        out_f = arr.astype(np.float32) * vig + grain[f % len(grain)]
        writer.write(np.clip(out_f, 0, 255).astype(np.uint8))

    writer.close()
    print(f"rendered {out}")


if __name__ == "__main__":
    main()
