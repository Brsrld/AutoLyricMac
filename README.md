# AutoLyricMac

Native macOS app that turns a YouTube music URL into a vertical 1080x1920 lyric video, with local preview and (later) publishing to YouTube Shorts and Instagram Reels.

## Status

**Step 1 — project skeleton.** Minimal SwiftUI app + local Python engine with a health check. No AI, media, or publishing integrations yet.

## Structure

| Path | Purpose |
|---|---|
| `MacApp/` | Native SwiftUI macOS app (Swift Package) |
| `Engine/` | Local Python engine (downloads, analysis, rendering — later steps) |
| `References/` | Reference material and design samples |
| `Output/` | Rendered videos (git-ignored) |
| `Cache/` | Downloaded/intermediate media (git-ignored) |
| `Logs/` | Engine and app logs (git-ignored) |
| `Docs/` | Project documentation |

## Running

Start the engine:

```sh
python3 Engine/engine.py serve
```

Build and launch the app:

```sh
cd MacApp
swift run
```

The app shows **Engine Connected** when the engine's health endpoint (`http://127.0.0.1:8765/health`) responds with `{"status": "ok"}`.

## Requirements

- macOS with Apple Silicon
- Xcode 26+ (Swift 6)
- Python 3.9+ (system Python is fine for this step)
