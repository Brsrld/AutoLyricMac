# Services, Providers and Credentials

Do not request every account at the beginning. Implement the adapter first and request credentials only when the feature is ready to test. Store secrets in macOS Keychain or an ignored local config—never tracked source.

For every request, state: service, exact feature, required credential/approval, storage, current cost category from official pricing, revocation method, and a free/local alternative.

## Local tools

- Xcode/Swift: native app, signing, AVPlayer, Keychain, OAuth callbacks.
- Homebrew: development dependency installation when needed.
- FFmpeg/ffprobe: conversion, compositing, rendering, validation.
- yt-dlp: authorized-source adapter only; no circumvention features.
- Python 3.12 project-local virtual environment.
- MLX Whisper/WhisperX or forced alignment: local vocal/lyric timing.
- librosa or equivalent: beats, onsets, energy, structural hints.

## Stock media

Create one protocol with Pexels as primary photo/video source, Pixabay as secondary, and Unsplash as optional photography source. Rank results together. Never use Google Images or arbitrary scraping.

## Lyrics

Use a provider interface supporting plain and synchronized lyrics where legitimate. Include local cache, candidate ranking, alternate recordings, user corrections, and fallback. Do not build a public lyrics redistribution database.

## Language model

Claude Code builds the app, but Claude Max is not an application API key. The app must work without a paid LLM using deterministic/local fallbacks. Add an optional replaceable Anthropic API provider later for interpretation, translation, queries, style selection, and metadata. Never reuse Claude Code login tokens.

## Optional image generation

AI media is fallback-only when stock is inadequate, a doodle asset is missing, or the user requests it. Implement the interface and stock-only path first. Potential adapters include fal.ai, Replicate, or local generation. Prefer a reusable curated doodle library over daily regeneration.

## Publishing accounts

- YouTube: Google Cloud project, YouTube Data API, OAuth client, user authorization. Start private/unlisted; tokens in Keychain.
- Instagram: eligible professional account, correct Meta relationship, Meta developer app, OAuth and publishing permissions. Official APIs only.
- Temporary storage: Cloudflare R2 or another S3-compatible provider only when Instagram requires remote HTTPS media; upload, publish, confirm, and delete.

Do not request Google/Meta/storage credentials during the visual prototype phases.
