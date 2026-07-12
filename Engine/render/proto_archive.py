#!/usr/bin/env python3
"""Archive Collage 15-second prototype (Phase 0).

Three lyric-phrase scenes on a warm paper artboard: one monochrome archival
photo as a framed object + translucent grey block per scene, slow drift and
push, fade-through-white transitions, grain/flicker, EN+TR subtitles on
irregular cream tape strips. Lyric: "Oh Shenandoah" (traditional, public
domain). All placement is deterministic.
"""

import numpy as np
from PIL import Image

from proto_common import (
    FONT_TYPEWRITER, FPS, H, OUTPUT_DIR, VideoWriter, W, alpha_paste,
    cover_resize, drop_shadow, ease_in_out, find_job_audio, lerp,
    load_photo, make_grain_frames, mono_archive, paper_canvas, paper_sticker,
    vignette_map,
)

DURATION = 15.0
SCENE_LEN = 5.0
FADE = 0.45  # fade-through-white at scene boundaries

SCENES = [
    {
        "slug": "train_smoke",
        "crop": (0.165, 0.135, 0.94, 0.935),
        "photo_w": 0.66, "photo_pos": (0.07, 0.16), "rot": -1.0,
        "block": {"pos": (0.66, 0.42), "size": (0.30, 0.24),
                  "color": (120, 118, 114), "alpha": 200},
        "drift": ((0, 0), (0, -36)), "zoom": (1.0, 1.045),
        "lines": ("Oh Shenandoah, I long to hear you",
                  "Şenandoa, sesini duymayı özlüyorum"),
        "sub_pos": (0.14, 0.565),
    },
    {
        "slug": "railway_fog",
        "crop": None,
        "photo_w": 0.56, "photo_pos": (0.36, 0.10), "rot": 0.8,
        "block": {"pos": (0.10, 0.55), "size": (0.24, 0.30),
                  "color": (60, 58, 56), "alpha": 235},
        "drift": ((-24, 0), (18, 22)), "zoom": (1.04, 1.0),
        "lines": ("Away, you rolling river",
                  "Uzaklara, akıp giden nehir"),
        "sub_pos": (0.30, 0.60),
    },
    {
        "slug": "lone_road",
        "crop": (0.075, 0.10, 0.925, 0.905),
        "photo_w": 0.74, "photo_pos": (0.13, 0.22), "rot": -0.6,
        "block": {"pos": (0.62, 0.12), "size": (0.28, 0.20),
                  "color": (200, 197, 192), "alpha": 170},
        "drift": ((0, 18), (0, -18)), "zoom": (1.0, 1.05),
        "lines": ("Across the wide Missouri",
                  "Geniş Missouri'nin ötesine"),
        "sub_pos": (0.20, 0.66),
    },
]


def build_scene_layer(scene, oversize=1.10):
    """Pre-composed oversized artboard for one scene (photo+block+shadow)."""
    bw, bh = int(W * oversize), int(H * oversize)
    board = Image.fromarray(paper_canvas()).resize((bw, bh), Image.BILINEAR)

    photo = mono_archive(load_photo(scene["slug"], scene["crop"]))
    pw = int(bw * scene["photo_w"])
    ratio = photo.height / photo.width
    ph = int(pw * ratio)
    ph = min(ph, int(bh * 0.62))
    photo = cover_resize(photo, pw, ph)

    px = int(bw * scene["photo_pos"][0])
    py = int(bh * scene["photo_pos"][1])

    # translucent block behind/beside the photo
    blk = scene["block"]
    bx, by = int(bw * blk["pos"][0]), int(bh * blk["pos"][1])
    bw_, bh_ = int(bw * blk["size"][0]), int(bh * blk["size"][1])
    block = Image.new("RGBA", (bw_, bh_), (*blk["color"], blk["alpha"]))
    board.paste(block, (bx, by), block)

    # photo with slight rotation + drop shadow
    rotated = photo.convert("RGBA").rotate(scene["rot"], expand=True,
                                           resample=Image.BICUBIC,
                                           fillcolor=(0, 0, 0, 0))
    shadow, pad, off = drop_shadow(rotated.size)
    board.paste(shadow, (px - pad + off[0], py - pad + off[1]), shadow)
    board.paste(rotated, (px, py), rotated)
    return board


def sticker_for(scene, idx):
    en = paper_sticker(scene["lines"][0], FONT_TYPEWRITER, 44,
                       bg=(237, 226, 198), rotation=-1.2, seed=40 + idx)
    tr = paper_sticker(scene["lines"][1], FONT_TYPEWRITER, 40,
                       bg=(240, 231, 206), rotation=0.9, seed=70 + idx,
                       text_fill=(74, 70, 64))
    return en, tr


def main():
    audio = find_job_audio()
    out = OUTPUT_DIR / "archive_collage_proto.mp4"
    writer = VideoWriter(out, audio, audio_offset=63.0, duration=DURATION)

    layers = [build_scene_layer(s) for s in SCENES]
    stickers = [sticker_for(s, i) for i, s in enumerate(SCENES)]
    grain = make_grain_frames(strength=4.5)
    vig = vignette_map(0.16)
    total = int(DURATION * FPS)
    rng = np.random.default_rng(2024)
    flicker = 1.0 + np.cumsum(rng.normal(0, 0.004, total)).clip(-0.02, 0.02)

    for f in range(total):
        t = f / FPS
        idx = min(int(t // SCENE_LEN), len(SCENES) - 1)
        local = (t - idx * SCENE_LEN) / SCENE_LEN
        scene, layer = SCENES[idx], layers[idx]

        e = ease_in_out(local)
        z = lerp(*scene["zoom"], e)
        dx = lerp(scene["drift"][0][0], scene["drift"][1][0], e)
        dy = lerp(scene["drift"][0][1], scene["drift"][1][1], e)

        lw, lh = layer.size
        cw, ch = int(W / z), int(H / z)
        cx = (lw - cw) / 2 + dx
        cy = (lh - ch) / 2 + dy
        cx = max(0, min(lw - cw, cx))
        cy = max(0, min(lh - ch, cy))
        frame_img = layer.crop((int(cx), int(cy), int(cx) + cw, int(cy) + ch))
        if (cw, ch) != (W, H):
            frame_img = frame_img.resize((W, H), Image.BILINEAR)
        arr = np.asarray(frame_img.convert("RGB")).copy()

        # subtitles (fade in over first 0.5 s of each scene, stay)
        en, tr = stickers[idx]
        sub_a = min(1.0, local * SCENE_LEN / 0.5)
        sx, sy = int(W * scene["sub_pos"][0]), int(H * scene["sub_pos"][1])
        if sub_a >= 1.0:
            alpha_paste(arr, en, (sx, sy))
            alpha_paste(arr, tr, (sx + 26, sy + en.height - 8))
        elif sub_a > 0:
            faded_en = en.copy()
            faded_en.putalpha(faded_en.getchannel("A").point(lambda v: int(v * sub_a)))
            faded_tr = tr.copy()
            faded_tr.putalpha(faded_tr.getchannel("A").point(lambda v: int(v * sub_a)))
            alpha_paste(arr, faded_en, (sx, sy))
            alpha_paste(arr, faded_tr, (sx + 26, sy + en.height - 8))

        # grade: flicker + vignette + grain
        out_f = arr.astype(np.float32) * flicker[f] * vig
        out_f += grain[f % len(grain)]

        # fade through white at scene boundaries (and hold off at t=0)
        boundary = min(t % SCENE_LEN, SCENE_LEN - (t % SCENE_LEN))
        if boundary < FADE and not (t < FADE and idx == 0):
            w_amt = (1.0 - boundary / FADE) * 0.92
            out_f = out_f * (1 - w_amt) + 248.0 * w_amt

        writer.write(np.clip(out_f, 0, 255).astype(np.uint8))

    writer.close()
    print(f"rendered {out}")


if __name__ == "__main__":
    main()
