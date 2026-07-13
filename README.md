# AutoLyricMac 🎬🎵

Turn any authorized YouTube song into a polished, vertical **lyric video**
(1080×1920 @ 30 fps) for Instagram Reels and YouTube Shorts — fully on-device
on Apple Silicon, with one click.

> Paste a URL → the app downloads the audio, finds the best segment, extracts
> and word-aligns the lyrics, plans scenes from their *meaning*, gathers
> licensed or AI-drawn visuals, renders a styled video, and publishes it.

## ✨ Features

- **One-click pipeline** — download → segment → lyrics → alignment → scene
  plan → media → render, as a single `Create Video` button (each stage also
  runs standalone)
- **Two hand-crafted styles**, tuned against real reference videos:
  - **Archive Collage** — centered editorial artwork on paper, 1–3 framed
    photos per scene, rhythm-locked image rotation on bass/drum onsets,
    clean cuts between lines
  - **Doodle Memory** — every scene is an original AI-drawn illustration
    (FLUX) in a wobbly ink style, colored by the lyric's emotion, animated
    with a hand-drawn "line boil", plus per-word handwritten sticker lyrics
- **Serious lyric sync** — Demucs vocal separation + `whisper-large-v3-turbo`
  word timestamps + monotonic windowed matching (repetitive folk lyrics stay
  in order) + synced-LRC fallback; uncertain lines are flagged, never hidden
- **Lyrics from anywhere** — LRCLIB, local `.lrc/.txt`, paste-in manually, or
  automatic transcription from the song itself when nothing else exists
- **Meaning-driven scenes** — deterministic TR/EN lexicon planner, optional
  Claude semantics (per-line emotion/subjects/queries) and a free-text
  **theme** field that steers imagery
- **Licensed or generated media** — Pexels/Pixabay/Unsplash with ranking,
  perceptual dedup, per-scene pools (no image ever repeats across scenes),
  full attribution history; fal.ai FLUX as fallback or as the Doodle painter
- **Manual control everywhere** — per-line corrections, paste-in-order
  Turkish translations, exclude any image, regenerate media, segment
  override, style/duration changes
- **Publishing** — YouTube (official OAuth + resumable upload) and Instagram
  Reels (official Graph API + temporary R2 object that is deleted right
  after publish); captions and hashtags from one field
- **Local & frugal** — engine binds to 127.0.0.1 only; secrets live in the
  macOS Keychain; every paid API result (Claude, FLUX) is cached so the same
  input is never paid for twice

## 🏗 Architecture

| Path | What lives there |
|---|---|
| `MacApp/` | SwiftUI app (SPM). Auto-starts/stops the engine; Keychain; history UI |
| `Engine/engine.py` | Loopback HTTP engine: jobs, lyrics/plan endpoints, publishing |
| `Engine/lyrics/` | Providers, LRC parsing, Demucs+Whisper alignment, store |
| `Engine/plan/` | Semantics (lexicon + optional Claude) and the scene planner |
| `Engine/media/` | Stock providers, ranking, dedup, crop, FLUX generation |
| `Engine/render/` | Archive & Doodle renderers, doodle library, validators |
| `Engine/publish/` | YouTube OAuth/upload, Instagram Graph + R2 temp storage |
| `Docs/` | Spec, style guide, phase plan, project state, troubleshooting |

The app never needs a terminal: it launches the Python engine itself and
everything renders locally through FFmpeg (H.264/AAC, fast-start, validated
against the output contract with QA frames).

## 🚀 Setup

```sh
scripts/setup.sh        # Homebrew deps + venv + tests + release build
cd MacApp && swift run  # start the app
```

Requirements: Apple Silicon Mac, Homebrew (`ffmpeg`, `yt-dlp`,
`python@3.12`), Xcode command line tools. First alignment downloads Whisper
weights (~1.6 GB) locally; Demucs weights arrive on first vocal separation.

### Optional keys (all stored in your Keychain, never in the repo)

| Key | Unlocks | Cost |
|---|---|---|
| Pexels / Pixabay / Unsplash | licensed stock photos | free |
| Anthropic API | per-line scene semantics + smarter queries | ~¢1 per song, cached |
| fal.ai | AI-drawn Doodle scenes / stock fallback | ~$0.003 per image, cached |
| Google OAuth client | YouTube upload | free quota |
| Meta app token + Cloudflare R2 | Instagram Reels | free tier |

## ⚖️ Licensing & ethics

- A URL grants no reuse rights: every download requires an explicit
  authorization acknowledgement in the UI, and the pipeline only processes
  media you own or are licensed to use
- Stock media comes only from official provider APIs, with creator/license
  attribution recorded per asset; AI-generated scenes are labeled as such
- No passwords, no browser automation, no scraping, no DRM circumvention;
  publishing uses official OAuth/Graph APIs exclusively

## 🧪 Tests

```sh
Engine/.venv/bin/python -m unittest discover -s Engine/tests   # 170+ tests
cd MacApp && swift test
```

See `Docs/TROUBLESHOOTING.md` when something misbehaves, and
`Docs/PROJECT_STATE.md` for the full build history.
