# AutoLyricMac

Native macOS app that turns a YouTube music URL into a vertical 1080x1920 lyric video, with local preview and (later) publishing to YouTube Shorts and Instagram Reels.

This application only processes music or media the user owns, licenses, or is authorized to reuse. The UI requires an explicit authorization acknowledgement before any media is downloaded.

## Status

**Phases 0–9 implemented** (see `Docs/PROJECT_STATE.md`): authorized audio
ingestion, segment selection, lyrics with mlx-whisper word alignment and
persistent corrections/Turkish translations, deterministic scene planning,
licensed stock media (Pexels/Pixabay/Unsplash) with attribution, both final
renderers (Archive Collage, Doodle Memory), history/regeneration/cleanup,
and official-API publishing to YouTube and Instagram. Pending user steps:
visual approval of the two style renders and live publishing credential
tests. See `Docs/TROUBLESHOOTING.md` when something misbehaves.

The full flow: paste an authorized URL → confirm authorization → ingest →
analyze segment → fetch + align lyrics (edit/translate as needed) → build
scene plan → fetch licensed media → render → preview → publish.

## Structure

| Path | Purpose |
|---|---|
| `MacApp/` | Native SwiftUI macOS app (Swift Package) |
| `Engine/` | Local Python engine (HTTP API on 127.0.0.1:8765, loopback only) |
| `References/` | Reference material and design samples |
| `Output/` | Rendered videos (git-ignored) |
| `Cache/` | Downloaded/intermediate media, `Cache/jobs/<job-id>/` (git-ignored) |
| `Logs/` | Engine and app logs (git-ignored) |
| `Docs/` | Project documentation |

## Setup (one-time)

```sh
scripts/setup.sh   # Homebrew deps + venv + tests + release build
```

or manually:

```sh
brew install ffmpeg yt-dlp python@3.12
python3.12 -m venv Engine/.venv
Engine/.venv/bin/pip install -r Engine/requirements.txt
```

## Running

```sh
cd MacApp
swift run
```

The app launches the engine itself (no separate Terminal needed), waits for the health endpoint, retries once on startup failure, and stops the engine on quit. The engine also exits on its own if the app process dies.

## Engine API (127.0.0.1:8765)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /inspect` | `{url}` → metadata (id, title, uploader, duration, thumbnail) without downloading |
| `POST /jobs` | `{url, authorized: true}` → start audio-ingestion job |
| `GET /jobs/<id>` | Job state, progress, message, result path/duration |
| `POST /jobs/<id>/cancel` | Cancel a running job |

## Tests

```sh
Engine/.venv/bin/python -m unittest discover -s Engine/tests   # engine logic
cd MacApp && swift test                                        # app logic
```

## Requirements

- macOS with Apple Silicon
- Xcode 26+ (Swift 6)
- Homebrew: `ffmpeg`, `yt-dlp`, `python@3.12`
