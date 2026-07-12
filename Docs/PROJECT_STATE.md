# Project State

Maintained in-repo so any session (or developer) can continue without external
context. Update this file whenever a phase completes.

Product spec: `CLAUDE.md` (repo root). Style rules: `Docs/STYLE_GUIDE.md`.
Phase plan and acceptance criteria: `Docs/PHASES_AND_ACCEPTANCE.md`.
Services/credentials policy: `Docs/SERVICES_AND_KEYS.md`.

## Completed

| Milestone | Commit | Notes |
|---|---|---|
| Step 1 — skeleton | `1f6cdd8` | SwiftUI app (SPM) + Python health engine on 127.0.0.1:8765 |
| Step 2 — ingestion | `c7ab2ee` | Auto engine lifecycle, /inspect metadata, authorized download jobs (yt-dlp → ffmpeg AAC/M4A → ffprobe), authorization checkbox, error taxonomy, 33 tests |
| Phase 0 — prototypes | `815e086` | `Docs/REFERENCE_ANALYSIS.md`; Archive Collage + Doodle Memory 15 s 1080x1920 prototypes (`Engine/render/`), output-contract validator; **user approved both** |
| Phase 1 — MVP gaps | `b7485a4` | AVAudioPlayer preview + in-app activity log; all Phase 1 acceptance criteria verified |
| Phase 2 — analysis | `ab14b13` | librosa analysis (tempo/beats/onsets/energy/sections/repetition), pure `select_segment` scorer with reasoning, `analyze` job kind, Segment Selection UI with manual override; verified end-to-end |

## Environment

- Apple Silicon (M-series), macOS 26.x, Xcode 26.x, Swift 6.x
- Homebrew at `/opt/homebrew`: `ffmpeg`, `yt-dlp`, `python@3.12`
- Engine venv: `Engine/.venv` (Python 3.12; yt-dlp, Pillow, numpy, librosa, soundfile)
- Run: `cd MacApp && swift run` (app auto-starts/stops the engine; no Terminal server)
- Tests: `Engine/.venv/bin/python -m unittest discover -s Engine/tests` and `cd MacApp && swift test`

## Licensing guardrails already in place

- Authorization acknowledgement gates every download; loopback-only engine
- Prototype media: Wikimedia Commons PD/CC0 only, recorded in `References/proto_media/ATTRIBUTION.json`
- Reference videos in `References/*.mp4` are third-party and git-ignored
- Test audio: Big Buck Bunny (CC-BY, user-confirmed) in `Cache/jobs/<id>/`

## Next: Phase 3 — Lyrics and synchronization

Per `Docs/PHASES_AND_ACCEPTANCE.md`: provider abstraction with ranking/cache,
canonical lyrics storage, line/word alignment with confidence (Apple-Silicon
Whisper, e.g. mlx-whisper — ask the user before downloading model weights),
user corrections, optional Turkish translation, and both subtitle systems
(Archive tape strips, Doodle handwritten stickers).
Acceptance: correct closely-timed words, visible uncertainty, safe-zone
wrapping, persisted edits, phone-size readability.
