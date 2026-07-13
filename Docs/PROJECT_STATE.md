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
| Phase 4 — planning & media | `3ada36e`…`8bf85fc` | EN+TR lexicon semantics (LLM-optional interface), deterministic phrase-driven scene planner (energy bands, beat micro-motion, style rules, automatic preset recommendation with reasoning), Pexels/Pixabay/Unsplash adapters with fallback chain, ranking + hard rejects (no enlargement/stretch, no <1080p or too-short video, watermark tags), dHash dedup, attribution store, subject-aware crop + adaptation strategies, `plan`/`media` jobs + `/plan` endpoint, Scene Plan & Media UI with Keychain-held keys; live Pexels test verified |
| Phase 5 — Archive render | see below | Final Archive Collage renderer + `render` job + UI; awaiting user visual approval |
| Phase 6 — Doodle render | see below | Doodle library + Doodle Memory renderer; awaiting user visual approval |

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

## Phase 4 acceptance evidence

- Visuals relate to lyrics: lexicon semantics feed per-scene queries
  ("Rain on the window" → "rain on window glass"); verified on real
  aligned lyrics via the HTTP `plan` job.
- No repeats/watermarks/enlargement/stretching: ranking hard-rejects
  (unit-tested), dHash dedup skips perceptual duplicates and reused refs,
  photos must exceed 1080x1920 after size verification of the actual file.
- Landscape adaptation: subject-aware attention crop, blur-fill, or
  Archive layered-frame decisions (unit-tested); never stretch.
- Provider fallback: failing provider is skipped with recorded error
  (unit-tested); missing keys produce a clean human-readable job error.
- E2E: plan job over HTTP on real data; media job happy path with a
  stubbed provider fetched 4/4 scenes with attribution + adaptation.

- Live provider test (2026-07-13, user-supplied Pexels key, now in
  Keychain as `AutoLyricMac`/`pexels_api_key`): photo + video search OK;
  full HTTP media job fetched 4/4 scenes with high-res portrait photos,
  correct attribution, and visually lyric-relevant results (embrace for
  "Hold me close", walking-in-field for "Walking home…").

## Phase 5 — Archive Collage renderer (implemented, awaiting user approval)

`render` job kind renders the media-annotated plan into the final video.
Pure `scene_layout` enforces the style guide (photos 55–90 % width as framed
objects, rotation 0.3–1.5°, grey/black/white translucent blocks, position
banks for consecutive variety, zoom ≤1.10x); transitions/beat pulses/
overlays come from the plan; EN+TR paper strips avoid faces (may lap the
photo's bottom edge, collage-style). 18 s test render passes the output
contract; QA frames inspected. **User must watch and approve
`Output/videos/deadbeef_archiveCollage_*.mp4` (or a fresh render).**

## Phase 6 — Doodle Memory renderer (implemented, awaiting user approval)

Curated 19-asset procedural doodle library (`Engine/render/doodle_library.py`)
covering all spec categories, tag-based selection; renderer warm-grades
full-frame media (subject-crop/blur-fill, never stretch), anchors figure
doodles on the lower third and sky doodles up top, slide-in/breathe/beat
bounce, word-timed handwritten stickers, phrase cut/paper wipe/sticker pop.
18 s test render passes the contract. **User approval pending.**
Known behavior: after editing a lyric line, run Align again so doodle word
stickers pick up the corrected words (they use aligned word tokens).

## Phase 7 — History and regeneration (complete)

ProjectStore in `Cache/projects.db` records every ingest, plan settings and
rendered output; `GET /projects`, delete, and `POST /cleanup` endpoints; the
app shows History with resume (restores lyrics + plan), open video, reveal,
delete, Regenerate Media (avoids all previous picks), per-scene exclude
(persists across regenerations), and cache cleanup.
Acceptance verified E2E: history + outputs survive engine restart;
corrections persist (Phase 3 store); regenerate produced 4/4 brand-new
assets with exclusions honored; cleanup removed an orphan job dir and a
stale preview while the active project and all rendered videos survived.

## Phase 8 — YouTube publishing (implemented; live test pending user)

Official OAuth 2.0 (PKCE + loopback redirect on 127.0.0.1:8767) with
tokens in Keychain, resumable uploads with retry/backoff and progress,
privacy selection, publish history, result URL in the app. Offline tests
cover the whole flow with injected transport; endpoint smoke test passed
(400s, path safety, not-connected error).
**Pending (needs the user):** create a Google Cloud project, enable the
YouTube Data API v3, create an OAuth client (type: Desktop app), then in
the app open Publish → Connect YouTube, paste client id/secret, sign in,
and run one private test upload. Cost: free quota (uploads cost ~1600
quota units of the 10k/day default). Revocation: Google Account →
Security → Third-party access; Disconnect in the app deletes tokens.

## Next: Phase 9 — Instagram publishing

Official Meta Graph API with an eligible professional account, temporary
HTTPS object storage (S3-compatible adapter), container publish/poll,
cleanup. Needs Meta developer app + eligible account when ready to test.
