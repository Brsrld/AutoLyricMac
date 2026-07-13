"""Both subtitle systems (Phase 3), per Docs/STYLE_GUIDE.md.

Archive Collage: original line and optional Turkish translation stacked on
separate irregular cream paper cutouts, dark editorial typewriter text,
slight rotation and shadow.

Doodle Memory: handwritten dark-navy words on individual irregular white
stickers; words appear at their aligned start times.

`render_subtitle_preview` composes either system over the selected audio
segment on a style-appropriate backdrop, producing a contract-valid MP4 and
QA frames — so wrapping, safe zones, translations, uncertainty markers, and
phone-size readability can be verified before full scene rendering exists.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.proto_common import (FPS, H, W, VideoWriter, ease_in_out,
                                 make_grain_frames, paper_canvas,
                                 paper_sticker, vignette_map)
from subtitles.layout import (SAFE_ZONE, Rect, block_size, place_block,
                              wrap_text)

FONT_TYPEWRITER = "/System/Library/Fonts/Supplemental/AmericanTypewriter.ttc"
FONT_HAND = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"

NAVY = (30, 41, 76)
INK = (58, 55, 50)
CREAM = (238, 228, 202)
CREAM_TR = (228, 216, 188)      # translation strip: slightly darker paper
STICKER_WHITE = (250, 248, 244)
UNCERTAIN_AMBER = (196, 138, 42)

EN_SIZE, TR_SIZE, HAND_SIZE = 40, 32, 52
LINE_GAP = 10


def _measurer(font_path, size):
    font = ImageFont.truetype(font_path, size)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def measure(text):
        box = probe.textbbox((0, 0), text, font=font)
        return box[2] - box[0]
    return measure


def _mark_uncertain(sticker):
    """Small amber dot in the sticker corner — uncertainty is never hidden."""
    draw = ImageDraw.Draw(sticker)
    m = 10
    draw.ellipse((m, m, m + 16, m + 16), fill=(*UNCERTAIN_AMBER, 230))
    return sticker


# ---------------------------------------------------------------------------
# Archive Collage: stacked tape strips (EN + optional TR)
# ---------------------------------------------------------------------------

def build_archive_subtitle(text, translation=None, seed=0, uncertain=False,
                           max_width=int(SAFE_ZONE.w * 0.92)):
    """RGBA block of stacked paper strips; returns (image, logical_size)."""
    measure_en = _measurer(FONT_TYPEWRITER, EN_SIZE)
    measure_tr = _measurer(FONT_TYPEWRITER, TR_SIZE)

    strips = []
    pad_w = 26 * 2  # paper_sticker horizontal padding
    for i, line in enumerate(wrap_text(text, max_width - pad_w, measure_en)):
        strips.append(paper_sticker(
            line, FONT_TYPEWRITER, EN_SIZE, text_fill=INK,
            bg=(235, 224, 200), pad=(14, 6), rotation=0.0,
            seed=seed * 31 + i, jitter=2))
    if translation:
        for i, line in enumerate(wrap_text(translation, max_width - pad_w,
                                           measure_tr)):
            strips.append(paper_sticker(
                line, FONT_TYPEWRITER, TR_SIZE, text_fill=(94, 88, 78),
                bg=(240, 231, 210), pad=(12, 5), rotation=0.0,
                seed=seed * 47 + i + 100, jitter=2))
    if not strips:
        return None, (0, 0)

    overlap = 6  # strips sit slightly into each other, like taped layers
    width = max(s.width for s in strips)
    height = sum(s.height for s in strips) - overlap * (len(strips) - 1)
    block = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    y = 0
    for s in strips:
        block.alpha_composite(s, ((width - s.width) // 2, y))
        y += s.height - overlap
    if uncertain:
        block = _mark_uncertain(block)
    return block, (width, height)


# ---------------------------------------------------------------------------
# Doodle Memory: handwritten navy word stickers
# ---------------------------------------------------------------------------

def build_doodle_words(words, seed=0, uncertain=False,
                       max_width=int(SAFE_ZONE.w * 0.62)):
    """Individual word stickers in a flow layout.

    Returns (stickers, size) where stickers is a list of
    (rgba_image, (dx, dy), word_index) offsets inside the block.
    """
    gap = 8
    items = []
    x = y = row_h = 0
    for wi, word in enumerate(words):
        text = word if isinstance(word, str) else word.get("text", "")
        if not text:
            continue
        sticker = paper_sticker(
            text, FONT_HAND, HAND_SIZE, text_fill=NAVY, bg=STICKER_WHITE,
            pad=(9, 5), rotation=(-2.0, 1.5, -1.0, 2.0, 0.5)[(seed + wi) % 5],
            seed=seed * 53 + wi, jitter=6)
        if x > 0 and x + sticker.width > max_width:
            x, y = 0, y + row_h - 14
            row_h = 0
        items.append([sticker, (x, y), wi])
        x += sticker.width - 6   # word-blob cloud, refs-style tight rows
        row_h = max(row_h, sticker.height)
    if not items:
        return [], (0, 0)
    width = max(it[0].width + it[1][0] for it in items)
    height = max(it[0].height + it[1][1] for it in items)
    if uncertain:
        _mark_uncertain(items[0][0])
    return [(s, off, wi) for s, off, wi in items], (width, height)


def build_doodle_translation(text, seed=0, max_width=int(SAFE_ZONE.w * 0.86)):
    """Smaller handwritten Turkish strip stacked under the word block."""
    if not (text or "").strip():
        return None
    size = 44
    measure = _measurer(FONT_HAND, size)
    strips = []
    for i, line in enumerate(wrap_text(text, max_width - 32, measure)):
        strips.append(paper_sticker(
            line, FONT_HAND, size, text_fill=(58, 74, 120),
            bg=(252, 250, 246), pad=(18, 8),
            rotation=(1.2, -0.8, 0.5)[(seed + i) % 3],
            seed=seed * 71 + i + 500, jitter=3))
    if not strips:
        return None
    width = max(s.width for s in strips)
    height = sum(s.height for s in strips) - 6 * (len(strips) - 1)
    block = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    y = 0
    for s in strips:
        block.alpha_composite(s, ((width - s.width) // 2, y))
        y += s.height - 6
    return block


# ---------------------------------------------------------------------------
# Preview renderer
# ---------------------------------------------------------------------------

def _doodle_backdrop(seed=11):
    """Warm nostalgic gradient canvas (no stock media yet in Phase 3)."""
    ys = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    top = np.array([236, 205, 140], dtype=np.float32)     # amber light
    bottom = np.array([116, 112, 78], dtype=np.float32)   # muted olive
    base = np.broadcast_to(top * (1 - ys) + bottom * ys, (H, W, 3)).copy()
    rng = np.random.default_rng(seed)
    base += rng.normal(0.0, 2.0, size=(H, W, 1)).astype(np.float32)
    return np.clip(base, 0, 255).astype(np.uint8)


def _alpha_composite_into(frame, block, x, y, alpha=1.0):
    """Composite RGBA `block` into RGB numpy frame at (x, y) with extra alpha."""
    x, y = int(x), int(y)
    bw, bh = block.size
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + bw, W), min(y + bh, H)
    if x0 >= x1 or y0 >= y1:
        return
    ov = np.asarray(block, dtype=np.float32)[y0 - y:y1 - y, x0 - x:x1 - x]
    a = ov[..., 3:4] / 255.0 * alpha
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (region * (1 - a) + ov[..., :3] * a).astype(np.uint8)


def render_subtitle_preview(style, lines, audio_path, out_path,
                            duration, audio_offset=0.0, progress=None):
    """Render a subtitle-focused preview MP4 (1080x1920@30, AAC).

    `lines`: [{display_text, translation, start, end, confidence, uncertain,
    words: [{text, start, end}]}] with times relative to the segment start.
    Uncertain lines carry a small amber marker — never shown silently.
    Returns the list of QA frame paths written next to the video.
    """
    out_path = Path(out_path)
    ENTER, EXIT = 0.3, 0.25

    # Pre-build one block per line; placement varies deterministically.
    prepared = []
    for li, line in enumerate(lines):
        if line.get("start") is None or line.get("end") is None:
            continue  # never guess timing for unaligned lines
        text = line.get("display_text") or ""
        if not text.strip():
            continue
        uncertain = bool(line.get("uncertain"))
        preferred = ("lower", "center", "lower", "upper")[li % 4]
        if style == "doodleMemory":
            words = line.get("words") or []
            stickers, size = build_doodle_words(
                [w["text"] for w in words] or text.split(),
                seed=li, uncertain=uncertain)
            if not stickers:
                continue
            tr_block = build_doodle_translation(line.get("translation"),
                                                seed=li)
            tr_h = (tr_block.height + 10) if tr_block else 0
            rect = place_block((size[0], size[1] + tr_h),
                               preferred=preferred, seed=li)
            word_times = [w.get("start") for w in words] if words else []
            prepared.append({"kind": "words", "stickers": stickers,
                             "rect": rect, "line": line,
                             "word_times": word_times,
                             "translation": tr_block,
                             "words_height": size[1]})
        else:
            block, size = build_archive_subtitle(
                text, line.get("translation"), seed=li, uncertain=uncertain)
            if block is None:
                continue
            rect = place_block(size, preferred=preferred, seed=li)
            prepared.append({"kind": "block", "block": block,
                             "rect": rect, "line": line})

    backdrop = paper_canvas() if style == "archiveCollage" else _doodle_backdrop()
    grain = make_grain_frames(count=8, strength=4.0)
    vig = vignette_map(0.16)

    writer = VideoWriter(out_path, audio_path, audio_offset=audio_offset,
                         duration=duration)
    total = int(round(duration * FPS))
    qa_at = sorted({min(total - 1, int(total * f)) for f in
                    (0.08, 0.3, 0.5, 0.7, 0.92)})
    qa_paths = []
    try:
        for n in range(total):
            t = n / FPS
            frame = backdrop.copy()
            for item in prepared:
                line = item["line"]
                s, e = line["start"], line["end"]
                if not (s - ENTER <= t <= e + 0.01):
                    continue
                enter = min(1.0, max(0.0, (t - (s - ENTER)) / ENTER))
                exit_ = min(1.0, max(0.0, (e - t) / EXIT))
                alpha = ease_in_out(min(enter, exit_))
                if alpha <= 0.01:
                    continue
                rect = item["rect"]
                rise = (1.0 - ease_in_out(enter)) * 26  # gentle entrance rise
                if item["kind"] == "block":
                    _alpha_composite_into(frame, item["block"],
                                          rect.x, rect.y + rise, alpha)
                else:
                    for sticker, (dx, dy), wi in item["stickers"]:
                        wt = (item["word_times"][wi]
                              if wi < len(item["word_times"]) else None)
                        if wt is not None and t < wt:
                            continue  # word pops in at its aligned start
                        pop = 1.0 if wt is None else \
                            ease_in_out(min(1.0, max(0.0, (t - wt) / 0.16)))
                        _alpha_composite_into(
                            frame, sticker, rect.x + dx,
                            rect.y + dy + rise + (1 - pop) * 10, alpha * pop)
                    if item.get("translation") is not None:
                        tr = item["translation"]
                        tx = rect.x + (rect.w - tr.width) / 2
                        _alpha_composite_into(
                            frame, tr, tx,
                            rect.y + item["words_height"] + 10 + rise, alpha)
            arr = frame.astype(np.float32)
            arr *= vig
            arr += grain[n % len(grain)]
            frame = np.clip(arr, 0, 255).astype(np.uint8)
            writer.write(frame)
            if n in qa_at:
                qa = out_path.with_name(f"{out_path.stem}_qa_{n:04d}.png")
                Image.fromarray(frame).save(qa)
                qa_paths.append(str(qa))
            if progress and n % 30 == 0:
                progress(n / total, f"Rendering subtitle preview… {int(100 * n / total)}%")
    finally:
        writer.close()
    return qa_paths
