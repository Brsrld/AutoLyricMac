# Reference Analysis

Analyzed with ffprobe, temporal frame extraction (1–2 s intervals), contact
sheets, full-resolution frame inspection, and scene-change detection
(`select=gt(scene,0.25)`). Reference files live in `References/` (git-ignored;
third-party material, not redistributable).

## 1. Archive Collage — `archive_collage_reference.mp4`

**Technical.** 59.2 s, 720x720 (square!), 30 fps, H.264 yuv420p, AAC stereo.
Song: "500 Miles" (English lyric + Turkish translation subtitles). The square
frame is why the style guide demands a redesigned 1080x1920 tall artboard
rather than a centered square with bars.

**Canvas & composition.**
- Warm off-white paper canvas (~#f2f0ec) fills most of the frame; photos
  occupy typically 30–60% of the canvas — negative space is a core feature.
- One monochrome archival photo per scene acts as a movable framed object
  (sharp rectangular edges + soft drop shadow), never a full-bleed background.
- A second element is almost always present: a plain matte grey/dark block
  (translucent or opaque), offset to a side, sometimes overlapping the photo,
  sometimes floating alone. Occasionally two photos layer with offsets.
- Photo positions vary scene to scene: left-third, centered, right-high, etc.
  Sizes vary roughly 45–75% width in the square frame.

**Photography.** Monochrome; steam trains, rails from above, smoke plumes,
foggy landscapes, lone walking figures, empty roads, birds, seaside — a
melancholic travel/documentary mood. Softened contrast, lifted blacks, mild
grain; nothing glossy.

**Timing & motion.** Scene detection shows main content changes roughly every
2–5 s with clusters of micro-transitions between (block repositioning,
flicker, layered dissolves around 14–19 s). Motion inside a scene is slow
photo drift/push and slow block repositioning; no fast zooms, no glitches.
Several passages fade through near-white.

**Subtitles.** Two stacked lines — English on top, Turkish below — each line
sits on its own cream/tan highlight strip with slightly irregular edges and a
tiny shadow, like paper tape. Dark grey serif/typewriter-style text, small
(≈3% of frame height per line). Placement is dynamic: overlapping the lower
part of the photo or beside it, near the visual center of gravity; never a
fixed bottom box. Ends with small credit stickers ("directed by …").

## 2. Doodle Memory — `doodle_memory_reference.mp4`

**Technical.** 20.4 s, 720x1280 vertical, 30 fps, H.264 yuv420p, AAC stereo.
Turkish lyric ("su olsam / ateş olsam / göklerdeki güneş olsam / konuşmasam
taş olsam / yine de oynar mısın benimle?"). NOTE: the reference itself
letterboxes a landscape photo inside the vertical frame (black top/bottom);
our output must instead fill 1080x1920 edge to edge per the style guide.

**Grade.** Real photographs heavily warm-graded and posterized (strong palette
quantization, GIF-like): amber/yellow highlights, muted olive/green shadows,
faded browns, soft contrast, mild grain. Sunlit domestic scenes: kitchen
window with teapot on stove, sunlit living room, park bench, tree-lined path.

**Doodles.** Transparent hand-drawn characters composited INTO the scene:
mother figure standing at the sink, child sitting on the counter, water
pouring from the real faucet drawn as a cyan doodle, a sun doodle in the sky,
mother+child sitting on the real bench, a hugging pair on the path. Style:
cream/off-white fill (#efe9d3-ish), thick dark-navy (#1d2a52-ish) imperfect
outline of consistent width, simplified rounded forms, minimal facial detail
(dot eyes, simple nose), wobbly double-traced lines. Doodles occupy 30–70% of
frame height and always anchor to real surfaces/objects.

**Timing & motion.** Hard phrase cuts at 2.27 / 5.60 / 11.40 / 15.87 s →
scenes of 2.3–5.8 s, exactly one lyric phrase per scene. Background is a
still (or nearly still) photo; doodles hold position with subtle breathing;
cuts are clean with no long crossfades.

**Text.** Handwritten-style lowercase dark-navy words, each word (or 2–3 word
group) on its own irregular cream sticker blob with a rough white border;
words are scattered along the top/upper-right of the frame around the doodle,
loosely following reading order, never in a bottom box. Text is large
(≈4–5% frame height) and phone-readable.

## 3. Prototype implications (Phase 0)

| Aspect | Archive Collage proto | Doodle Memory proto |
|---|---|---|
| Canvas | 1080x1920 off-white paper, tall artboard layout | 1080x1920 full-bleed warm-graded photo |
| Content per scene | 1 mono photo (framed, shadow) + grey block(s) | photo + 1–2 interacting doodles |
| Scene length | 3–7 s (proto: ~5 s x 3 scenes) | 2.5–5.5 s (proto: ~3.75 s x 4 scenes) |
| Motion | slow drift/push <1.5° rotation, block reposition | still bg, doodle breathe 1–2%, slight rotate |
| Transition | soft crossfade / fade-through-white 0.25–0.8 s | hard cut / ≤0.35 s dissolve |
| Subtitles | serif/typewriter on cream tape strips, EN+TR stacked | handwritten navy on cream sticker blobs, scattered |
| Grade | mono, lifted blacks, grain, occasional flicker | warm amber/olive, posterized, grain |
| Audio | 15 s licensed audio segment with fades | same |
