# Implementation Phases and Acceptance Criteria

Complete phases sequentially. A phase is done only after its acceptance criteria are tested.

## Phase 0 — Reference analysis and prototypes

Inspect both references with ffprobe, temporal frames, and contact sheets; create `Docs/REFERENCE_ANALYSIS.md`; extract timing, transitions, typography, placement, grade, motion, and overlays. Render separate 15-second 1080x1920 Archive Collage and Doodle Memory prototypes with multiple states and readable subtitles.

Accept only if both are 30fps H.264/AAC playable MP4s with audio, no stretching/bars, technically validated, visually inspected via sample frames, and approved by the user.

## Phase 1 — Native macOS MVP and ingestion

Build SwiftUI UI, automatic local-engine lifecycle, URL validation/metadata, authorization acknowledgement, safe audio ingestion, progress/logs/cancellation, AVPlayer preview, and Finder reveal. Use multiple licensed assets when rendering begins.

Accept only if app builds/launches, no separate server command is needed, real metadata works, authorized audio is ffprobe-valid, cancellation/errors work, UI stays responsive, and paths are safe.

## Phase 2 — Audio analysis and segment selection

Add normalized metadata, BPM/beats/onsets/energy/sections, best 30/45/60s selection, fades, and manual start override.

Accept only if requested length is met, cuts avoid mid-word/clicks, selection reasoning is logged, override works, and main scenes do not cut on every beat.

## Phase 3 — Lyrics and synchronization

Add provider abstraction, ranking/cache, canonical lyrics, line/word alignment and confidence, corrections, Turkish translation, and both subtitle systems.

Accept only if words are correct and closely timed, uncertainty is visible, wrapping/safe zones work, translations fit, edits persist, and phone-size readability is verified.

## Phase 4 — Semantic planning and media relevance

Add meaning/emotion extraction, structured scene plans, several queries per scene, provider ranking/fallback, resolution/orientation checks, perceptual deduplication, subject-aware crop/fill, and attribution history.

Accept only if visuals relate to lyrics, repeats/watermarks/low-resolution enlargement/stretching are prevented, landscape adaptation is intelligent, and provider failure falls back cleanly.

## Phase 5 — Finalize Archive Collage

Implement artboard, negative space, varied framed photos, translucent blocks, monochrome analog treatment, slow editorial movement, and irregular paper subtitles.

Accept only if it does not resemble a basic slideshow, scenes typically last 3–7s, layout is legible vertically, and the user approves it.

## Phase 6 — Finalize Doodle Memory

Build the coherent semantic doodle library, warm grading, environment interaction, dynamic handwritten stickers, phrase cuts, and light animation.

Accept only if assets are consistent/transparent, interact with scenes, text placement varies safely, no gibberish appears, and the user approves it.

## Phase 7 — History and regeneration

Add persistent jobs/previews, regenerate all/media-only, exclude asset, change style/duration/start, lyric edits, reveal project, and safe cache cleanup.

Accept only if relaunch preserves history, corrections persist, duplicates are prevented, cancellation cleans temporaries, and active outputs survive cleanup.

## Phase 8 — YouTube publishing

Implement official OAuth, connect/disconnect, refresh, progress, metadata/privacy, result URL and retry. Accept after a private/unlisted test upload works and tokens are secured in Keychain.

## Phase 9 — Instagram publishing

Implement official Meta authorization, eligible account selection, temporary storage, processing polling, publish result, cleanup, and errors. Accept only after an official API test succeeds and temporary objects/tokens are handled securely.

## Phase 10 — Packaging and release

Automate dependency/engine setup, onboarding, settings, authorization notice, clean-checkout build, M4 Max verification, troubleshooting docs, and release build.

Final flow must work: open app → paste authorized URL → select duration/style → create/preview → save or publish. Both styles, lyrics, render, history, YouTube and Instagram must pass, with no manual background server and no exposed secrets.
