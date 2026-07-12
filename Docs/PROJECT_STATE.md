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
| Phase 3 — lyrics & sync | `d107c3a`…`7f5146c` | Lyrics providers (LRCLIB + local .lrc/.txt) with ranking and SQLite cache, canonical store with persistent corrections/Turkish translations, mlx-whisper word alignment with per-line/word confidence (uncertain + suspect flags), both subtitle systems (Archive tape strips EN+TR, Doodle navy word stickers) with safe-zone wrapping/dynamic placement, `lyrics`/`align`/`subtitle_preview` job kinds + `/lyrics` endpoints, Lyrics & Sync UI; 92 tests total; E2E verified |

## Environment

- Apple Silicon (M-series), macOS 26.x, Xcode 26.x, Swift 6.x
- Homebrew at `/opt/homebrew`: `ffmpeg`, `yt-dlp`, `python@3.12`
- Engine venv: `Engine/.venv` (Python 3.12; yt-dlp, Pillow, numpy, librosa, soundfile, mlx-whisper)
- Whisper weights: `mlx-community/whisper-base-mlx` (~150 MB, user-approved 2026-07-13) in `~/.cache/huggingface`
- Run: `cd MacApp && swift run` (app auto-starts/stops the engine; no Terminal server)
- Tests: `Engine/.venv/bin/python -m unittest discover -s Engine/tests` and `cd MacApp && swift test`
- Lyrics DB: `Cache/lyrics.db`; user lyric files go in `Cache/lyrics_local/` or the job dir
- Alignment test fixture: `Cache/jobs/deadbeef…` (locally synthesized `say` speech + matching .lrc — fully authorized)

## Licensing guardrails already in place

- Authorization acknowledgement gates every download; loopback-only engine
- Prototype media: Wikimedia Commons PD/CC0 only, recorded in `References/proto_media/ATTRIBUTION.json`
- Reference videos in `References/*.mp4` are third-party and git-ignored
- Test audio: Big Buck Bunny (CC-BY, user-confirmed) in `Cache/jobs/<id>/`

## Phase 3 acceptance evidence

- Words correct and closely timed: `say`-synthesized speech aligned at 100%
  match (module test) and 83% via HTTP E2E where one LRC line is deliberately
  never sung — that line gets no guessed timing and is flagged uncertain.
- Uncertainty visible: per-line confidence dots + badges in the UI, amber
  corner marker in renders, `suspect` banner when overall confidence is low.
- Safe zones/wrapping: 12 pure layout tests (force-break, collision
  avoidance, zone containment); QA frames inspected for both styles.
- Edits persist: corrections/translations survive store reopen (unit test)
  and flow into renders (verified in `Output/subtitle_previews/deadbeef_*`).
- Translations fit: TR strips wrap independently on their own cutouts.

## Next: Phase 4 — Semantic planning and media relevance

Per `Docs/PHASES_AND_ACCEPTANCE.md`: meaning/emotion extraction with a
deterministic/local fallback (LLM optional), structured scene plans,
several search queries per scene, stock-provider adapters (Pexels primary —
request the API key only when ready to test), ranking/fallback,
resolution/orientation checks, perceptual dedup, subject-aware crop/fill,
and attribution history.
