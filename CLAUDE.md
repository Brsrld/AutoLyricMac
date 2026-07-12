# AutoLyricMac Product Specification

## Goal

Build a native macOS application that runs locally on an Apple Silicon M4 Max Mac and creates vertical lyric videos for Instagram Reels and YouTube Shorts.

Normal user input:

- YouTube music URL
- 30, 45, or 60 seconds
- visual preset: `archiveCollage`, `doodleMemory`, or `automatic`
- save locally and, later, publish to YouTube and/or Instagram

The app validates the link, obtains authorized audio, identifies the song, finds and aligns lyrics, selects a strong segment, analyzes mood and energy, plans scenes, obtains licensed high-resolution media, renders locally, previews the result, and optionally publishes it.

## Output contract

- 9:16, 1080x1920, 30 fps
- MP4, H.264, AAC, yuv420p, fast-start
- no stretching, accidental black bars, clipped subtitles, or watermarks
- Apple VideoToolbox when reliable, with software fallback

## Architecture

- Native SwiftUI macOS frontend with URL entry, duration/style selection, progress, logs, cancellation, AVPlayer preview, history, settings, and publish controls.
- Local Python processing engine using localhost-only HTTP or JSON-lines IPC.
- FFmpeg/ffprobe, yt-dlp behind an authorized-source adapter, librosa or equivalent, Apple-Silicon-optimized Whisper/forced alignment, Pillow/OpenCV/Core Image, SQLite, and perceptual hashing.
- The app must launch and stop the engine automatically; no separate Terminal command in normal use.
- Rendering, audio analysis, crop/compositing, subtitles, effects, and previews stay local.

## Source and audio

- A URL never grants reuse rights. Require an authorization acknowledgement.
- Validate URL and metadata before download.
- Cache deterministically, use safe paths and subprocess argument arrays, prevent duplicates and shell injection, support cancellation, and validate outputs with ffprobe.
- Do not store browser cookies in the repository or add DRM/copyright-evasion behavior.

## Section selection

Choose the best complete 30/45/60-second section using chorus likelihood, repeated phrases, vocal presence, energy, onset density, boundaries, recognizability, and lyric completeness. Avoid mid-word cuts and add short fades. Provide advanced manual start-time override.

## Lyrics

Use replaceable providers and candidate ranking. Store canonical lyrics, line/word timings and confidence, allow corrections, and surface uncertainty. Support original lyrics and optional Turkish translation. Never silently display obviously wrong lyrics.

## Editing logic

- Main scene changes follow lyric meaning and phrase boundaries—not every beat.
- Beats drive subtle pulses, texture, or micro-motion.
- Energy increases can shorten scenes or strengthen movement.
- Scene plans are structured JSON containing timing, lyric, meaning, emotion, subjects, search queries, media preference, motion, transition, overlay, and subtitle placement.
- The app must have a deterministic/local fallback; an LLM provider is optional.

## Licensed stock media

Provider adapters: Pexels, Pixabay, and Unsplash (photos). Search photo/video where supported, prefer vertical high-resolution sources, rank semantic relevance and mood, reject blur/watermarks/logos/text-heavy or tiny media, deduplicate, and store provider/creator/source/license metadata.

Never scrape arbitrary websites. Prefer still images substantially above output size and video at least 1080 vertical. Never stretch landscape media: use subject-aware crop, tracking, blurred fill, layered collage, or framing.

## Presets and subtitles

Implement `docs/STYLE_GUIDE.md` faithfully. Explicit user selection overrides automatic selection.

Subtitle engine requirements:

- line-based plus optional word timing
- original plus optional translation
- safe-zone-aware wrapping and dynamic placement
- generated paper/sticker backgrounds and entrance/exit motion
- collision avoidance with faces and focal subjects
- readable at phone size and away from top/bottom/right interaction areas

## Renderer

Support stills, stock video, layered images, masks, alpha overlays, text, affine transforms, blur, grain, flicker, vignette, subtle shake, crossfades/cuts, paper textures, and doodles. Use deterministic compositions and reusable intermediates where helpful. Validate dimensions, fps, codecs, duration, audio, pixel format, and playability; export representative QA frames.

## Doodle library

Create a curated local transparent asset library before relying on per-video AI generation. Categories include people standing/sitting/talking/walking/hugging, parent-child, play, window/sky, cooking, water, fire, sun, stone, loneliness, distance, reunion, memory, and home. Normalize to cream/white fill, dark navy imperfect hand-drawn outline, consistent stroke, and transparent background.

## Persistence and security

Store jobs, lyrics/corrections, plans, assets and attribution, outputs, errors, and publish history locally in SQLite/SwiftData. Put secrets and OAuth tokens in Keychain, redact logs, bind services to localhost, validate URLs/paths, and clean temporary data.

## Publishing

- YouTube: official OAuth 2.0 and Data API, refresh tokens in Keychain, progress, metadata, privacy selection, private/unlisted testing, result URL, retryable errors.
- Instagram: official Meta/Instagram APIs and eligible professional account only. If remote HTTPS media is required, upload temporarily to an object-store adapter, publish/poll/confirm, then delete the object.
- Never use passwords, browser automation, private endpoints, or session-cookie hacks.

## Reliability and testing

Add retries/backoff, timeouts, cancellation, recovery, caching, duplicate prevention, provider fallback, human-readable errors, and detailed logs. Include unit tests for URL/path safety, scene timing, subtitle layout, media ranking and crop calculations; integration render tests, mocked provider tests, ffprobe validation, snapshots, and an end-to-end checklist. Never claim success without running the relevant build/test.

## Packaging

Deliver a normal macOS application with reproducible setup/build, automated engine lifecycle, paths independent of one developer machine, onboarding, and a copyright authorization acknowledgement.
