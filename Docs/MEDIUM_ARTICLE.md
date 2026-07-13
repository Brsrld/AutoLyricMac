# I Built a Machine That Turns Any Song Into an Instagram Reel (And It Argues With Drums)

*Paste a YouTube link. Go make coffee. Come back to a 1080×1920 lyric video with word-perfect subtitles, scenes cut to the song's* meaning*, images dancing to the actual drum hits — and a "Publish Reel" button. Here's how we built AutoLyricMac on a Mac, mostly locally, occasionally for less than a cent.*

![Rhythm-locked collage swaps](gifs/collage_rhythm.gif)
*Images rotating on bass hits. The drummer is now our art director.*

---

## The Itch

Lyric videos are a cottage industry on Reels and Shorts. The workflow, however, is medieval: hunt for lyrics, hand-time every line, dig through stock sites, wrestle After Effects. One video ≈ one afternoon.

The goal: **URL in, finished video out.** On-device, on Apple Silicon, no subscriptions — with a human allowed to meddle at any step, but never required to.

## The Shape of the Thing

Two halves, one handshake:

- A **SwiftUI app** that owns the UI, history, and your Keychain secrets — and babysits the engine (starts it on launch, kills it on quit; you never see a terminal).
- A **Python engine** pinned to `127.0.0.1`, where every heavy job lives: download, analyze, align, plan, fetch, draw, render, publish.

The unglamorous superpower: almost everything is a pure function with an injectable network layer, so 170+ unit tests run the whole factory offline. When OAuth, resumable uploads, and S3 signatures all have fake transports, 3 AM debugging becomes 3 PM debugging.

## Act I: Sixty Seconds of the Good Part

`yt-dlp` fetches the (user-authorized — the app literally makes you check a rights box) audio. Except YouTube sometimes slams the door: *"Sign in to confirm you're not a bot."* Our fallback chain: default client → iOS client disguise → the user's own browser session via the official `cookies-from-browser` flag. Polite persistence.

Then librosa dissects the track — tempo, beats, percussive onsets, energy curve, section repetition — and a scorer picks the best 30/45/60 seconds (chorus-ish, energetic, beat-aligned cuts, no mid-word chops).

## Act II: The Lyrics Saga, or: How a Turkish Folk Song Became Russian

This layer got rebuilt the most. Final pipeline:

1. **Find lyrics, three ways:** LRCLIB → your local `.lrc/.txt` → and if the internet shrugs, *the song itself*: we isolate the vocals and transcribe them. No lyrics found is no longer an error.
2. **Demucs vocal separation.** Drums smear Whisper's word timestamps. Feed it clean vocals instead and our test song jumped from 60% to **100% word match**.
3. **`whisper-large-v3-turbo` on MLX** — 18 seconds of audio aligned in ~4 seconds. Fun bug: the small model once declared a Turkish folk song to be Russian. We now double-check with a "does this *text* look Turkish?" heuristic. (It did.)
4. **Monotonic matching for repetitive lyrics.** Global alignment sees "bülbül bülbül bülbül" and glues every repeat to the first occurrence — timestamps travel back in time. Our matcher walks strictly forward: each repeat consumes the *next* occurrence. Causality restored.
5. **Honest uncertainty.** Lines the model couldn't hear get flagged orange, never silently faked. One click to correct; corrections persist forever.

## Act III: Scenes That Read the Room

Scenes cut on **sentences**, not beats — beats only drive micro-motion. Each line goes through a bilingual (EN/TR) lexicon that extracts subjects, emotion, and stock-search queries; add an Anthropic key and Claude Haiku does it with taste (*"Watch it fly by as the pendulum swings"* → `pendulum clock macro, moody light`). There's also a free-text **theme box** — write *"regret, passing time, lonely dark city"* and every scene, even instrumental ones, hunts imagery from that world.

![Calm collage scene](gifs/collage_calm.gif)
*Calm passage: one image, held long, breathing slowly. The "uzun hava" mode.*

## Act IV: Pixels — Rented, Pooled, Never Repeated

Photos come from Pexels/Pixabay/Unsplash behind one protocol, ranked by relevance × verticality × resolution headroom, with hard rejections (no upscaling, no stretching, no watermark-smelling tags) and perceptual-hash dedup. Every scene downloads one hero image plus two understudies, and the house rule is absolute: **an image appears in exactly one scene, ever.**

For the Doodle style we fired the stock sites entirely. Every scene is **drawn from scratch** by FLUX — storybook ink-and-gouache, thick navy outlines, palette chosen by the lyric's emotion (melancholy → rainy indigo, joy → sunny yellows). And because static drawings are boring:

![Line boil animation](gifs/doodle_boil.gif)
*"Line boil": three subtly warped copies cycling at 6 fps. Costs zero, looks alive.*

![Word stickers popping](gifs/doodle_words.gif)
*Each word pops onto its own paper blob exactly when it's sung.*

## Act V: Rhythm — A Metronome Is Not a Drummer

Version one swapped images on a beat grid. Feedback: "robotic." The fixes that made it feel *played* rather than scheduled:

- Swaps trigger on **percussive onsets** (actual bass/drum hits), cadence locked to the song's BPM — every 2 beats when energetic, every 4 when mellow, never during a sentence's first or last second (sentence changes and image changes colliding felt like a hiccup).
- Within a scene, the same 2–3 images just **rotate roles** — the big frame changes, the others shuffle — so swaps read as rhythm, not channel-zapping. Each swap cross-melts over 0.3s.
- Between sentences? **Clean cuts.** The new scene's different photo count and layout *is* the transition. (Also 15% faster to render. Everybody wins.)

The meta-lesson of this act: **aesthetics don't come from code review, they come from reference videos.** The user dropped 10 real references; we measured them frame by frame and turned the findings into unit-tested composition law — "photo width 55–90%", "rotation ≤ 0.35°" are literal asserts now.

## Act VI: Publishing Without Ever Typing a Password

- **YouTube:** OAuth with PKCE over a loopback redirect, refresh token in the Keychain, chunked resumable upload with backoff.
- **Instagram Reels:** the official Graph API wants a public HTTPS video URL, so the file visits a Cloudflare R2 bucket for ~90 seconds and gets deleted the moment Instagram confirms. The S3 SigV4 signer is 40 lines of stdlib. No boto3 was harmed.
- At one point the user pasted their actual Instagram password into the chat. We refused, pointed at the official token flow, and gently suggested changing that password. *Never give your password to an AI. Not even a charming one.*

Field-war story: R2 uploads kept dying with TLS handshake failures. Not Python's fault, not Cloudflare's — the machine's **antivirus was man-in-the-middling TLS** with its own certificate. Fix: route object-storage traffic through system `curl`, which trusts the local chain. Sometimes the bug is standing behind you.

## The Frugality Engine

Every paid API result is cached locally: Claude's scene directions (keyed by song+lyrics), translations (per line), FLUX images (by prompt hash). Rebuild the plan five times, pay once. Twenty dollars of credit is, in practice, hundreds of videos.

## What We'd Tell Past Us

1. **Injectable transports or tears.** Fake the network, test the factory offline.
2. **Never trust a model's output raw.** Language detection lies, alignment drifts, FLUX doodles its own gibberish captions. Every ML step got a validator and a human-override door.
3. **Short feedback loops beat good taste.** Every render exports QA frames; "second 14 looks wrong" iterates 100× faster than "I don't like it."
4. **Deterministic core, optional LLM glaze.** No keys? Still works. Keys? It sings.

---

*AutoLyricMac is SwiftUI + Python + FFmpeg + librosa + Demucs + MLX Whisper + FLUX + the official YouTube/Instagram APIs, running on an M-series Mac. Code: [github.com/Brsrld/AutoLyricMac](https://github.com/Brsrld/AutoLyricMac)*
