# AutoLyricMac

Native macOS app that turns a YouTube music URL into a vertical 1080x1920 lyric video, with local preview and (later) publishing to YouTube Shorts and Instagram Reels.

This application only processes music or media the user owns, licenses, or is authorized to reuse. The UI requires an explicit authorization acknowledgement before any media is downloaded.

## Status

**Step 2 + Phase 0 complete.** The app auto-starts the local Python engine, inspects YouTube URLs for metadata (no download), and can run an authorized audio-download test: yt-dlp → FFmpeg (AAC/M4A) → ffprobe verification, with progress and cancellation. Phase 0 adds reference analysis (`Docs/REFERENCE_ANALYSIS.md`) and two 15-second 1080x1920 style prototypes (`Engine/render/`, outputs in `Output/prototypes/`) rendered from public-domain/CC0 media (`References/proto_media/ATTRIBUTION.json`). No AI or publishing integrations yet.

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
