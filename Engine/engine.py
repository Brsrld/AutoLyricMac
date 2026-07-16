#!/usr/bin/env python3
"""AutoLyricMac local engine.

Step 2: source inspection (metadata without download) and an authorized
audio-ingestion pipeline (yt-dlp download -> ffmpeg convert -> ffprobe verify),
exposed over a loopback-only HTTP API the Mac app drives.

This engine only processes media the user owns, licenses, or is authorized to
reuse. It performs no DRM circumvention and stores no credentials or cookies.

Usage:
    python3 engine.py health                       # prints {"status": "ok"}
    python3 engine.py serve [--port N] [--parent-pid PID]

HTTP API (127.0.0.1 only):
    GET  /health                -> {"status": "ok", ...}
    POST /inspect               {"url": ...} -> metadata, no download
    POST /jobs                  {"url": ..., "authorized": true} -> {"job_id": ...}
                                {"kind": "analyze"|"lyrics"|"align"|"subtitle_preview", ...}
    GET  /jobs/<id>             -> job status/progress
    POST /jobs/<id>/cancel      -> request cancellation
    GET  /lyrics/<job_id>       -> canonical lyrics with timing/confidence
    POST /lyrics/<job_id>/line  {"line_index": N, "corrected_text"?, "translation"?}
    GET  /plan/<job_id>         -> stored scene plan (with media annotations)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DEFAULT_PORT = 8765
ENGINE_VERSION = "0.4"

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_JOBS_DIR = REPO_ROOT / "Cache" / "jobs"
LYRICS_DB_PATH = REPO_ROOT / "Cache" / "lyrics.db"
MEDIA_DB_PATH = REPO_ROOT / "Cache" / "media.db"
MEDIA_CACHE_DIR = REPO_ROOT / "Cache" / "media"
PROJECTS_DB_PATH = REPO_ROOT / "Cache" / "projects.db"
SUBTITLE_PREVIEW_DIR = REPO_ROOT / "Output" / "subtitle_previews"
VIDEO_OUTPUT_DIR = REPO_ROOT / "Output" / "videos"
SUBTITLE_STYLES = ("archiveCollage", "doodleMemory",
                   "polaroidWall", "minimalDark", "cinemaStill", "comicPop")
PLAN_STYLES = SUBTITLE_STYLES + ("automatic",)
RENDER_STYLES = ("archiveCollage", "doodleMemory",
                 "polaroidWall", "minimalDark", "cinemaStill", "comicPop")
# styles whose scenes are always fully AI-drawn (one image per scene)
FULL_AI_STYLES = ("doodleMemory", "comicPop")
# art directions for AI-drawn (Doodle template) scenes; see media/genai.py
ART_STYLES = ("storybook", "ghibli", "realistic", "watercolor",
              "anime", "oil", "caricature", "comic")


def _clean_art_style(value):
    """Return a valid art style or None (falls back to the plan default)."""
    v = str(value or "").strip()
    return v if v in ART_STYLES else None


def is_drawn_media(media):
    """True when a scene's media is an AI-drawn Doodle illustration.

    Photo styles (Archive family, Cinematic Still) must never show these;
    they are only valid while the plan style is doodleMemory.
    """
    if not media:
        return False
    if str(media.get("provider", "")).startswith("fal"):
        return str(Path(media.get("file_path") or "").name).startswith("drawn_")
    return False

# Minimum free disk space required before starting a download.
MIN_FREE_BYTES = 500 * 1024 * 1024

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# in-flight OAuth flows: state -> {"status": pending|connected|error, ...}
OAUTH_FLOWS = {}


def start_oauth_listener(client_id, client_secret, verifier, state):
    """One-shot loopback listener that finishes the YouTube OAuth flow."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from publish.youtube import (REDIRECT_PORT, PublishError,
                                 YouTubeConnector, exchange_code,
                                 parse_redirect)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                code = parse_redirect(self.path, state)
                tokens = exchange_code(client_id, client_secret, code,
                                       verifier)
                refresh = tokens.get("refresh_token")
                if not refresh:
                    raise PublishError(
                        "Google returned no refresh token. Remove the app at "
                        "myaccount.google.com/permissions and connect again.")
                YouTubeConnector().store_connection(client_id, client_secret,
                                                    refresh)
                OAUTH_FLOWS[state] = {"status": "connected",
                                      "message": "YouTube connected."}
                body, status = ("<html><body style='font-family:sans-serif'>"
                                "<h3>AutoLyricMac is connected to YouTube."
                                "</h3><p>You can close this window.</p>"
                                "</body></html>"), 200
            except PublishError as exc:
                OAUTH_FLOWS[state] = {"status": "error", "message": str(exc)}
                body, status = (f"<html><body><h3>Connection failed</h3>"
                                f"<p>{exc}</p></body></html>"), 400
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass  # never log OAuth query strings

    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), RedirectHandler)
    server.timeout = 300

    def serve_once():
        try:
            server.handle_request()
        finally:
            server.server_close()
        if OAUTH_FLOWS.get(state, {}).get("status") == "pending":
            OAUTH_FLOWS[state] = {"status": "error",
                                  "message": "Authorization timed out."}

    threading.Thread(target=serve_once, daemon=True).start()

HEALTH_PAYLOAD = {"status": "ok", "version": ENGINE_VERSION}


# --------------------------------------------------------------------------
# Tool discovery
# --------------------------------------------------------------------------

def find_tool(name):
    """Locate an external tool, preferring Homebrew's install location."""
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which(name)


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


# --------------------------------------------------------------------------
# URL validation (pure, unit-tested)
# --------------------------------------------------------------------------

def validate_youtube_url(url):
    """Return the 11-char video id for a well-formed YouTube URL, else None.

    Accepts watch/shorts/youtu.be/music forms. Only http(s) schemes.
    """
    if not url or not isinstance(url, str) or len(url) > 2048:
        return None
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    video_id = None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live)/([A-Za-z0-9_-]{11})$", parsed.path)
            if m:
                video_id = m.group(2)
    elif host == "youtu.be":
        m = re.match(r"^/([A-Za-z0-9_-]{11})$", parsed.path)
        if m:
            video_id = m.group(1)

    if video_id and VIDEO_ID_RE.match(video_id):
        return video_id
    return None


# --------------------------------------------------------------------------
# Metadata mapping (pure, unit-tested)
# --------------------------------------------------------------------------

def build_metadata(info, original_url):
    """Map a yt-dlp info dict to the app's metadata payload."""
    return {
        "valid": True,
        "video_id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail_url": info.get("thumbnail"),
        "original_url": original_url,
    }


# --------------------------------------------------------------------------
# Error classification (pure, unit-tested)
# --------------------------------------------------------------------------

def classify_ytdlp_error(message):
    """Map a yt-dlp error message to (code, human-readable text)."""
    msg = (message or "").lower()
    if "sign in to confirm your age" in msg or "age-restricted" in msg or "age restricted" in msg:
        return "restricted", "This video is age-restricted and cannot be processed."
    if "available in your country" in msg or "geo restriction" in msg or ("region" in msg and "block" in msg):
        return "restricted", "This video is not available in your region."
    if "video unavailable" in msg or "private video" in msg or "removed" in msg or "does not exist" in msg:
        return "unavailable", "This video is unavailable (private, removed, or nonexistent)."
    if ("unable to download" in msg and "webpage" in msg) or "network" in msg or "timed out" in msg \
            or "temporary failure in name resolution" in msg or "getaddrinfo" in msg or "connection" in msg:
        return "network", "Network problem while contacting the source. Check your connection."
    if "unsupported url" in msg or "is not a valid url" in msg:
        return "invalid_url", "That does not look like a supported video URL."
    return "ytdlp_failed", f"Source tool failed: {message}"


# --------------------------------------------------------------------------
# Safe path generation (pure, unit-tested)
# --------------------------------------------------------------------------

def new_job_id():
    return uuid.uuid4().hex


def job_dir_for(job_id, base_dir=None):
    """Return the directory for a job id, refusing anything unsafe.

    Job ids are engine-generated uuid hex; anything else (traversal attempts,
    separators, empty) raises ValueError.
    """
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        raise ValueError(f"invalid job id: {job_id!r}")
    base = Path(base_dir) if base_dir else CACHE_JOBS_DIR
    path = (base / job_id).resolve()
    if path.parent != base.resolve():
        raise ValueError("job path escaped base directory")
    return path


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

class Job:
    """A background job: audio ingestion ("download") or analysis ("analyze")."""

    def __init__(self, url=None, video_id=None, kind="download",
                 source_job_id=None, target_seconds=None, start_override=None,
                 artist=None, title=None, style=None, segment_start=None,
                 api_keys=None):
        self.id = new_job_id()
        self.kind = kind
        self.url = url
        self.video_id = video_id
        self.source_job_id = source_job_id
        self.target_seconds = target_seconds
        self.start_override = start_override
        self.artist = artist
        self.title = title
        self.style = style
        self.segment_start = segment_start
        # provider API keys are held in memory for this job only —
        # never logged, never persisted, never included in snapshots
        self.api_keys = api_keys or {}
        self.regenerate = False          # media job: refetch every scene
        self.exclude_assets = []         # media job: [(provider, ref), ...]
        self.art_style = None            # plan/media job: AI-draw art style
        self.ai_images = False           # media job: AI-draw collage images
        self.motion_effects = False      # render job: flicker + breathing
        self.sync_offset = 0.0           # render job: lyrics↔audio nudge (s)
        self.publish_meta = {}           # publish job: title/desc/privacy
        self.state = "queued"          # queued|downloading|converting|analyzing|verifying|done|error|cancelled
        self.progress = 0.0            # 0..1
        self.message = "Queued"
        self.error_code = None
        self.audio_path = None
        self.audio_duration = None
        self.audio_format = None
        self.result = None             # kind-specific extras (analysis payload)
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return {
                "job_id": self.id,
                "kind": self.kind,
                "state": self.state,
                "progress": round(self.progress, 4),
                "message": self.message,
                "error_code": self.error_code,
                "audio_path": self.audio_path,
                "audio_duration": self.audio_duration,
                "audio_format": self.audio_format,
                "result": self.result,
            }

    def set(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def fail(self, code, message):
        self.set(state="error", error_code=code, message=message)

    # ---- pipeline ----

    def run(self):
        try:
            if self.kind == "analyze":
                self._run_analysis()
            elif self.kind == "lyrics":
                self._run_lyrics()
            elif self.kind == "align":
                self._run_align()
            elif self.kind == "translate":
                self._run_translate()
            elif self.kind == "subtitle_preview":
                self._run_subtitle_preview()
            elif self.kind == "plan":
                self._run_plan()
            elif self.kind == "media":
                self._run_media()
            elif self.kind == "render":
                self._run_render()
            elif self.kind == "publish_youtube":
                self._run_publish_youtube()
            elif self.kind == "publish_instagram":
                self._run_publish_instagram()
            else:
                self._run_pipeline()
        except CancelledError:
            self.set(state="cancelled", error_code="cancelled", message="Job cancelled.")
            self._cleanup_dir()
        except Exception as exc:  # last-resort guard so a job never hangs
            self.fail("ytdlp_failed", f"Unexpected engine error: {exc}")

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise CancelledError()

    def _cleanup_dir(self):
        if self.kind == "analyze":
            # analysis writes into the source job's dir; remove only our segment
            try:
                for p in job_dir_for(self.source_job_id).glob(
                        f"segment_*{self.id[:8]}.m4a"):
                    p.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
            return
        if self.kind == "subtitle_preview":
            try:
                for p in SUBTITLE_PREVIEW_DIR.glob(f"*_{self.id[:8]}.mp4"):
                    p.unlink(missing_ok=True)
            except OSError:
                pass
            return
        if self.kind != "download":
            return  # lyrics/align own no files outside the shared database
        try:
            shutil.rmtree(job_dir_for(self.id), ignore_errors=True)
        except ValueError:
            pass

    def _run_pipeline(self):
        import yt_dlp

        free = shutil.disk_usage(str(REPO_ROOT)).free
        if free < MIN_FREE_BYTES:
            self.fail("disk_space",
                      f"Not enough free disk space ({free // (1024*1024)} MB free, "
                      f"{MIN_FREE_BYTES // (1024*1024)} MB required).")
            return

        if FFMPEG is None or FFPROBE is None:
            self.fail("ffmpeg_failed", "FFmpeg/ffprobe not found. Install with: brew install ffmpeg")
            return

        job_dir = job_dir_for(self.id)
        job_dir.mkdir(parents=True, exist_ok=True)

        # ---- download best audio (deterministic filename: source.<ext>) ----
        self.set(state="downloading", message="Downloading audio…")

        def progress_hook(d):
            self._check_cancel()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes")
                if total and done:
                    # Download occupies 0..0.7 of overall progress.
                    frac = min(done / total, 1.0)
                    self.set(progress=0.7 * frac,
                             message=f"Downloading audio… {int(frac * 100)}%")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(job_dir / "source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
            "retries": 2,
            "socket_timeout": 20,
        }
        source_info = {}
        try:
            source_info = robust_extract(self.url, ydl_opts,
                                         download=True) or {}
        except CancelledError:
            raise
        except yt_dlp.utils.DownloadError as exc:
            code, human = classify_ytdlp_error(str(exc))
            self.fail(code, human)
            self._cleanup_dir()
            return

        self._check_cancel()
        sources = sorted(job_dir.glob("source.*"))
        if not sources:
            self.fail("ytdlp_failed", "Download finished but no source file was produced.")
            return
        source = sources[0]

        # ---- convert to a stable format (AAC in .m4a) via ffmpeg ----
        self.set(state="converting", progress=0.75, message="Converting to M4A (AAC)…")
        audio_out = job_dir / "audio.m4a"
        cmd = [FFMPEG, "-y", "-nostdin", "-i", str(source),
               "-vn", "-c:a", "aac", "-b:a", "192k", str(audio_out)]
        result = self._run_subprocess(cmd)
        if result is None:
            raise CancelledError()
        if result.returncode != 0:
            tail = (result.stderr or "")[-500:]
            self.fail("ffmpeg_failed", f"FFmpeg conversion failed: {tail}")
            return

        # ---- verify with ffprobe ----
        self.set(state="verifying", progress=0.92, message="Verifying audio file…")
        probe_cmd = [FFPROBE, "-v", "error", "-print_format", "json",
                     "-show_format", "-show_streams", str(audio_out)]
        probe = self._run_subprocess(probe_cmd)
        if probe is None:
            raise CancelledError()
        if probe.returncode != 0:
            self.fail("ffmpeg_failed", "ffprobe could not verify the converted file.")
            return
        try:
            info = json.loads(probe.stdout)
            duration = float(info["format"]["duration"])
            codec = next((s.get("codec_name") for s in info.get("streams", [])
                          if s.get("codec_type") == "audio"), None)
        except (KeyError, ValueError, json.JSONDecodeError):
            self.fail("ffmpeg_failed", "ffprobe returned an unreadable result.")
            return
        if not codec or duration <= 0:
            self.fail("ffmpeg_failed", "Converted file has no valid audio stream.")
            return

        # keep only the converted artifact
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass

        # project history: relaunches restore this ingest (Phase 7)
        from projects import ProjectStore
        ProjectStore(PROJECTS_DB_PATH).record_ingest(
            self.id, url=self.url, video_id=self.video_id,
            title=source_info.get("title"),
            uploader=source_info.get("uploader") or source_info.get("channel"),
            duration=duration, audio_path=str(audio_out))

        self.set(state="done", progress=1.0,
                 message=f"Audio ready ({codec}, {duration:.1f}s).",
                 audio_path=str(audio_out),
                 audio_duration=duration,
                 audio_format=codec)

    def _run_analysis(self):
        """Analyze an ingested job's audio and cut the best segment."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from analysis.audio_analysis import analyze_audio, select_segment, cut_segment

        if FFMPEG is None or FFPROBE is None:
            self.fail("ffmpeg_failed", "FFmpeg/ffprobe not found.")
            return
        try:
            source_dir = job_dir_for(self.source_job_id)
        except ValueError:
            self.fail("not_found", "Unknown source job id.")
            return
        source_audio = source_dir / "audio.m4a"
        if not source_audio.exists():
            self.fail("not_found", "Source job has no ingested audio file.")
            return

        self.set(state="analyzing", message="Analyzing audio…")

        def progress(frac, msg):
            self._check_cancel()
            self.set(progress=0.75 * frac, message=msg)

        try:
            analysis = analyze_audio(source_audio, FFMPEG, progress=progress)
        except CancelledError:
            raise
        except Exception as exc:
            self.fail("analysis_failed", f"Audio analysis failed: {exc}")
            return

        self._check_cancel()
        self.set(progress=0.8, message="Selecting the best segment…")
        choice = select_segment(analysis, self.target_seconds,
                                start_override=self.start_override)
        for line in choice.reasons:
            print(f"[engine] job {self.id} segment: {line}", flush=True)

        segment_path = source_dir / f"segment_{int(self.target_seconds)}s_{self.id[:8]}.m4a"
        self.set(progress=0.85, message="Cutting segment with fades…")
        cut = cut_segment(source_audio, segment_path, choice, FFMPEG)
        if cut.returncode != 0:
            self.fail("ffmpeg_failed", f"Segment cut failed: {(cut.stderr or '')[-300:]}")
            return

        self._check_cancel()
        self.set(state="verifying", progress=0.95, message="Verifying segment…")
        probe = self._run_subprocess([FFPROBE, "-v", "error", "-print_format", "json",
                                      "-show_format", str(segment_path)])
        if probe is None:
            raise CancelledError()
        try:
            seg_duration = float(json.loads(probe.stdout)["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError):
            self.fail("ffmpeg_failed", "Segment verification failed.")
            return
        if abs(seg_duration - self.target_seconds) > 0.5:
            self.fail("ffmpeg_failed",
                      f"Segment duration {seg_duration:.2f}s does not match "
                      f"the requested {self.target_seconds}s.")
            return

        self.set(state="done", progress=1.0,
                 message=f"Segment ready: {choice.start:.1f}s–{choice.end:.1f}s "
                         f"({analysis['tempo_bpm']:.0f} BPM).",
                 audio_path=str(segment_path),
                 audio_duration=seg_duration,
                 audio_format="aac",
                 result={
                     "tempo_bpm": round(analysis["tempo_bpm"], 1),
                     "track_duration": round(analysis["duration"], 2),
                     "beat_count": len(analysis["beats"]),
                     "section_count": len(analysis["sections"]),
                     "segment_start": choice.start,
                     "segment_end": choice.end,
                     "score": round(choice.score, 4),
                     "reasons": choice.reasons,
                 })

    def _source_audio(self):
        """Path to the source job's ingested audio, or fail the job."""
        try:
            source_dir = job_dir_for(self.source_job_id)
        except ValueError:
            self.fail("not_found", "Unknown source job id.")
            return None
        audio = source_dir / "audio.m4a"
        if not audio.exists():
            self.fail("not_found", "Source job has no ingested audio file.")
            return None
        return audio

    def _probe_duration(self, path):
        probe = self._run_subprocess([FFPROBE, "-v", "error", "-print_format",
                                      "json", "-show_format", str(path)])
        if probe is None:
            raise CancelledError()
        try:
            return float(json.loads(probe.stdout)["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return None

    def _run_lyrics(self):
        """Search lyric providers, rank candidates, store the best match."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lyrics.providers import LyricsProviderError, default_providers
        from lyrics.ranking import rank_candidates
        from lyrics.store import LyricsStore

        source_audio = self._source_audio()
        if source_audio is None:
            return
        track_duration = self._probe_duration(source_audio)

        store = LyricsStore(LYRICS_DB_PATH)
        artist, title = self.artist or "", self.title or ""
        cache_key = f"search:{artist.lower()}|{title.lower()}|{int(track_duration or 0)}"

        self.set(state="analyzing", progress=0.1,
                 message=f"Searching lyrics for “{title}”…")
        candidates = store.cached_search(cache_key)
        if candidates is None:
            candidates = []
            errors = []
            for provider in default_providers(REPO_ROOT,
                                              source_audio.parent):
                self._check_cancel()
                try:
                    candidates.extend(provider.search(artist, title,
                                                      duration=track_duration))
                except LyricsProviderError as exc:
                    errors.append(str(exc))
            if not candidates and errors:
                self.fail("lyrics_failed", " ".join(errors))
                return
            store.store_search(cache_key, candidates)

        self._check_cancel()
        self.set(progress=0.7, message="Ranking lyric candidates…")
        ranked = rank_candidates(candidates, artist, title, track_duration)
        if not ranked:
            # no provider hit: extract lyrics from the song's own vocals
            self.set(progress=0.75,
                     message="No lyrics found online — transcribing from "
                             "the song itself (Demucs + Whisper)…")
            try:
                from lyrics.align import transcribe_words, words_to_lines
                from lyrics.models import LyricsCandidate
                from lyrics.separate import separate_vocals
                vocals = separate_vocals(
                    source_audio,
                    log=lambda m: print(f"[engine] job {self.id} lyrics: {m}",
                                        flush=True)) or source_audio
                self._check_cancel()
                words, lang = transcribe_words(vocals, ffmpeg=FFMPEG)
                from lyrics.translate import looks_turkish
                texts = words_to_lines(words)
                if lang != "tr" and looks_turkish(texts):
                    words, lang = transcribe_words(vocals, language="tr",
                                                   ffmpeg=FFMPEG)
                    texts = words_to_lines(words)
                if len(texts) < 2:
                    raise ValueError("no singable vocals detected")
                from lyrics.ranking import RankedCandidate
                cand = LyricsCandidate(provider="transcription",
                                       artist=artist, title=title,
                                       plain_text="\n".join(texts))
                ranked = [RankedCandidate(cand, 0.5,
                                          ["transcribed from the audio"])]
            except Exception as exc:
                self.fail("lyrics_not_found",
                          f"No lyrics found online and transcription failed "
                          f"({exc}). You can use Enter Lyrics Manually.")
                return
        best = ranked[0]
        for line in best.reasons:
            print(f"[engine] job {self.id} lyrics: {line}", flush=True)
        store.save_lyrics(self.source_job_id, best.candidate,
                          score=best.score, track_duration=track_duration)
        payload = store.get_lyrics(self.source_job_id)
        self.set(state="done", progress=1.0,
                 message=f"Lyrics ready: {len(payload['lines'])} lines "
                         f"({'synced' if payload['synced'] else 'plain'}, "
                         f"score {best.score:.2f}).",
                 result={
                     "chosen": best.candidate.summary(),
                     "score": round(best.score, 3),
                     "line_count": len(payload["lines"]),
                     "synced": payload["synced"],
                     "candidates": [
                         {**r.candidate.summary(), "score": round(r.score, 3)}
                         for r in ranked[:5]
                     ],
                 })

    def _run_align(self):
        """Word-align stored lyrics against the ingested audio (mlx-whisper)."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lyrics.align import align_lyrics, transcribe_words
        from lyrics.store import LyricsStore

        source_audio = self._source_audio()
        if source_audio is None:
            return
        store = LyricsStore(LYRICS_DB_PATH)
        payload = store.get_lyrics(self.source_job_id)
        if payload is None:
            self.fail("not_found", "Fetch lyrics before aligning.")
            return

        # isolate vocals first: instruments blur Whisper's word timestamps
        self.set(state="analyzing", progress=0.05,
                 message="Separating vocals for precise timing (Demucs)…")
        align_audio = source_audio
        try:
            from lyrics.separate import separate_vocals
            vocals = separate_vocals(
                source_audio,
                log=lambda m: print(f"[engine] job {self.id} align: {m}",
                                    flush=True))
            if vocals is not None:
                align_audio = vocals
        except Exception:
            pass

        self.set(progress=0.35,
                 message="Transcribing vocals (local Whisper)…")
        try:
            from lyrics.translate import looks_turkish as _ltr
            lang_hint = "tr" if _ltr([ln["display_text"]
                                      for ln in payload["lines"]]) else None
            asr_words, source_lang = transcribe_words(align_audio,
                                                      language=lang_hint,
                                                      ffmpeg=FFMPEG)
        except Exception as exc:
            self.fail("align_failed", f"Transcription failed: {exc}")
            return
        self._check_cancel()

        self.set(progress=0.7, message="Aligning lyrics to audio…")
        from lyrics.align import align_hybrid
        line_texts = [ln["display_text"] for ln in payload["lines"]]
        # IMMUTABLE synced-LRC spans (re-parsed from raw_lrc, never the stored
        # line timings — a prior align may have overwritten those).
        lrc_spans = {int(k): v for k, v in (payload.get("lrc_spans") or {}).items()} \
            if payload["synced"] else {}
        word_spans = {int(k): v
                      for k, v in (payload.get("lrc_word_spans") or {}).items()} \
            if payload["synced"] else {}
        # A provider LRC can be timed to a different master than this audio
        # (lyrics land over an instrumental section). Detect that global
        # offset from the vocal-energy envelope — text-independent, so it
        # works even on foreign songs ASR can't read — and shift the LRC to
        # match the real vocals before aligning.
        # vocal-activity mask (from separated vocals) so the plan/renderer can
        # keep subtitles off the screen during real instrumental sections,
        # even when the LRC times a line there. Written per source job.
        try:
            from lyrics.align import vocal_energy_envelope, vocal_segments
            _env, _hop = vocal_energy_envelope(align_audio, ffmpeg=FFMPEG)
            segs = vocal_segments(_env, _hop)
            (job_dir_for(self.source_job_id) / "vocal_segments.json").write_text(
                json.dumps(segs), encoding="utf-8")
            print(f"[engine] job {self.id} align: {len(segs)} vocal "
                  f"segment(s) detected for subtitle gating", flush=True)
        except Exception as exc:
            print(f"[engine] job {self.id} align: vocal segmenting skipped "
                  f"({exc})", flush=True)
        if lrc_spans:
            try:
                from lyrics.align import (estimate_lrc_offset,
                                          vocal_energy_envelope)
                env, hop = vocal_energy_envelope(align_audio, ffmpeg=FFMPEG)
                off, best, zero = estimate_lrc_offset(env, hop, lrc_spans)
                if abs(off) >= 0.3 and best >= 0.55 and best - zero >= 0.1:
                    lrc_spans = {li: (s + off,
                                      (e + off) if e is not None else None)
                                 for li, (s, e) in lrc_spans.items()
                                 if s is not None}
                    word_spans = {li: [(t, ws + off) for t, ws in ws_list]
                                  for li, ws_list in word_spans.items()}
                    print(f"[engine] job {self.id} align: LRC vs audio "
                          f"offset {off:+.2f}s (fit {best:.2f} vs {zero:.2f}) "
                          f"— shifted LRC to match vocals", flush=True)
                else:
                    print(f"[engine] job {self.id} align: LRC offset check "
                          f"{off:+.2f}s (fit {best:.2f} vs {zero:.2f}); "
                          f"no shift", flush=True)
            except Exception as exc:
                print(f"[engine] job {self.id} align: offset check skipped "
                      f"({exc})", flush=True)
        # precise ASR word timing where heard + clean LRC skeleton elsewhere,
        # offset-corrected and clamped monotonic (foreign/instrumental songs
        # fall back to the LRC timeline instead of scrambling it). Enhanced
        # LRCs carry per-word timings — used directly so words pop on beat.
        aligned, matched_ratio, mean_confidence = align_hybrid(
            line_texts, lrc_spans, asr_words, word_spans=word_spans)
        print(f"[engine] job {self.id} align: hybrid — "
              f"{matched_ratio:.0%} of lines matched to ASR word timing"
              f"{', LRC skeleton' if lrc_spans else ''}", flush=True)
        store.apply_alignment(self.source_job_id, aligned, matched_ratio,
                              mean_confidence)

        translated = 0
        refreshed = store.get_lyrics(self.source_job_id)
        uncertain = sum(1 for ln in refreshed["lines"] if ln["uncertain"])
        suspect = refreshed["suspect"]
        message = (f"Alignment done: {matched_ratio:.0%} of words matched, "
                   f"{uncertain} uncertain line(s).")
        if suspect:
            message += " Lyrics may not match this recording — please review."
        self.set(state="done", progress=1.0, message=message,
                 result={
                     "matched_ratio": matched_ratio,
                     "mean_confidence": mean_confidence,
                     "uncertain_lines": uncertain,
                     "suspect": suspect,
                     "asr_word_count": len(asr_words),
                     "language": source_lang,
                 })

    def _run_translate(self):
        """On-demand Turkish translation of the stored lyrics.

        Not automatic (foreign songs get no silent translation) — the user
        triggers this. Prefers Claude for poetic quality (cached, so a
        re-run is free), falls back to the offline Argos models. Turkish
        songs are left untouched; user-entered translations are preserved
        unless `force` is set.
        """
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lyrics.store import LyricsStore
        from lyrics.translate import looks_turkish

        store = LyricsStore(LYRICS_DB_PATH)
        payload = store.get_lyrics(self.source_job_id)
        if payload is None:
            self.fail("not_found", "Fetch lyrics before translating.")
            return
        lines = payload["lines"]
        texts = [ln["display_text"] for ln in lines]
        if looks_turkish(texts):
            self.set(state="done", progress=1.0,
                     message="Bu şarkı zaten Türkçe — çeviriye gerek yok.",
                     result={"translated": 0, "already_turkish": True})
            return
        todo = [(ln["line_index"], ln["display_text"]) for ln in lines
                if ln["display_text"].strip()
                and (self.regenerate
                     or not (ln.get("translation") or "").strip())]
        if not todo:
            self.set(state="done", progress=1.0,
                     message="Tüm satırların Türkçe çevirisi zaten var.",
                     result={"translated": 0})
            return

        self.set(state="analyzing", progress=0.2,
                 message=f"{len(todo)} satır Türkçe'ye çevriliyor…")
        indices = [li for li, _ in todo]
        src_texts = [t for _, t in todo]
        translated = 0

        # 1) Claude — natural/poetic, cached so a repeat costs nothing
        key = None
        try:
            from publish.youtube import Keychain
            key = Keychain().get("anthropic_api_key")
        except Exception:
            pass
        if key:
            try:
                import llm_cache
                from lyrics.translate import claude_translate_lines
                ck = llm_cache.key_for("tr", *src_texts)
                results = llm_cache.get_json(ck)
                cached = results is not None
                if results is None:
                    results = claude_translate_lines(src_texts, key)
                    llm_cache.put_json(ck, results)
                self._check_cancel()
                for li, tr in zip(indices, results):
                    tr = (tr or "").strip()
                    if tr:
                        store.update_line(self.source_job_id, li,
                                          translation=tr)
                        translated += 1
                print(f"[engine] job {self.id} translate: Claude "
                      f"{translated} line(s)"
                      f"{' (cache, ücretsiz)' if cached else ''}", flush=True)
            except Exception as exc:
                print(f"[engine] job {self.id} translate: Claude failed "
                      f"({exc}); trying Argos", flush=True)
                translated = 0

        # 2) offline Argos fallback
        if translated == 0:
            self.set(progress=0.5,
                     message="Yerel çeviri modeliyle çevriliyor (Argos)…")
            from lyrics.translate import (ensure_argos_pair,
                                          fill_missing_translations)
            src = ("ar" if any("؀" <= c <= "ۿ"
                               for c in " ".join(src_texts)) else "en")
            log = lambda m: print(f"[engine] job {self.id} translate: {m}",
                                  flush=True)
            try:
                ensure_argos_pair(src, "tr", log=log)
            except Exception:
                pass
            translated, _ = fill_missing_translations(
                store, self.source_job_id, src, log=log)

        if translated == 0:
            self.fail("translate_failed",
                      "Çeviri yapılamadı. Anthropic anahtarı ekleyebilir "
                      "veya çevirileri elle girebilirsin.")
            return
        refreshed = store.get_lyrics(self.source_job_id)
        have = sum(1 for ln in refreshed["lines"]
                   if (ln.get("translation") or "").strip())
        self.set(state="done", progress=1.0,
                 message=f"{translated} satır Türkçe'ye çevrildi "
                         f"({have}/{len(refreshed['lines'])} satırda çeviri).",
                 result={"translated": translated,
                         "total": len(refreshed["lines"])})

    def _run_subtitle_preview(self):
        """Render a subtitle-only preview MP4 for the chosen style/segment."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lyrics.store import LyricsStore
        from subtitles.render import render_subtitle_preview

        source_audio = self._source_audio()
        if source_audio is None:
            return
        payload = LyricsStore(LYRICS_DB_PATH).get_lyrics(self.source_job_id)
        if payload is None:
            self.fail("not_found", "Fetch and align lyrics before previewing.")
            return

        seg_start = float(self.segment_start or 0.0)
        duration = float(self.target_seconds)
        seg_end = seg_start + duration
        lines = []
        for ln in payload["lines"]:
            if ln["start"] is None or ln["end"] is None:
                continue
            if ln["end"] <= seg_start or ln["start"] >= seg_end:
                continue
            words = [{"text": w["text"],
                      "start": None if w["start"] is None
                      else max(0.0, w["start"] - seg_start),
                      "end": None if w["end"] is None
                      else w["end"] - seg_start}
                     for w in ln["words"]]
            lines.append({
                "display_text": ln["display_text"],
                "translation": ln["translation"],
                "start": max(0.0, ln["start"] - seg_start),
                "end": min(duration, ln["end"] - seg_start),
                "uncertain": ln["uncertain"],
                "words": words,
            })
        if not lines:
            self.fail("no_timed_lines",
                      "No aligned lyric lines fall inside this segment.")
            return

        self.set(state="analyzing", progress=0.05,
                 message=f"Rendering {self.style} subtitle preview…")
        SUBTITLE_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        out_path = SUBTITLE_PREVIEW_DIR / f"{self.source_job_id[:8]}_{self.style}_{self.id[:8]}.mp4"

        def progress(frac, msg):
            self._check_cancel()
            self.set(progress=0.05 + 0.85 * frac, message=msg)

        try:
            qa_frames = render_subtitle_preview(
                self.style, lines, source_audio, out_path,
                duration=duration, audio_offset=seg_start, progress=progress)
        except CancelledError:
            out_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            out_path.unlink(missing_ok=True)
            self.fail("render_failed", f"Subtitle preview failed: {exc}")
            return

        self._check_cancel()
        self.set(state="verifying", progress=0.95, message="Verifying preview…")
        seg_duration = self._probe_duration(out_path)
        if seg_duration is None or abs(seg_duration - duration) > 0.5:
            self.fail("ffmpeg_failed", "Rendered preview failed verification.")
            return
        self.set(state="done", progress=1.0,
                 message=f"Subtitle preview ready ({len(lines)} lines).",
                 audio_path=str(out_path),
                 audio_duration=seg_duration,
                 result={"output_path": str(out_path),
                         "qa_frames": qa_frames,
                         "line_count": len(lines),
                         "style": self.style})

    def _plan_path(self):
        return job_dir_for(self.source_job_id) / "scene_plan.json"

    def _run_plan(self):
        """Analyze audio + stored lyrics into a structured scene plan."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from analysis.audio_analysis import analyze_audio
        from lyrics.store import LyricsStore
        from plan.planner import build_scene_plan

        source_audio = self._source_audio()
        if source_audio is None:
            return
        payload = LyricsStore(LYRICS_DB_PATH).get_lyrics(self.source_job_id)
        if payload is None or not payload.get("aligned"):
            self.fail("not_found", "Fetch and align lyrics before planning scenes.")
            return

        seg_start = float(self.segment_start or 0.0)
        seg_end = seg_start + float(self.target_seconds)

        self.set(state="analyzing", progress=0.1,
                 message="Analyzing audio for scene planning…")
        try:
            analysis = analyze_audio(source_audio, FFMPEG,
                                     progress=lambda f, m: self.set(
                                         progress=0.1 + 0.6 * f, message=m))
        except Exception as exc:
            self.fail("analysis_failed", f"Audio analysis failed: {exc}")
            return
        self._check_cancel()

        self.set(progress=0.8, message="Planning scenes from lyric meaning…")
        from projects import ProjectStore as _PS
        project = _PS(PROJECTS_DB_PATH).get_project(self.source_job_id) or {}
        title_hint = " ".join(filter(None, [
            project.get("title") or payload.get("title"),
            payload.get("artist")]))
        theme = self.publish_meta.get("theme", "")
        theme_queries = []
        if theme:
            # user-provided theme drives song-level queries + LLM directions
            title_hint = f"{title_hint} — theme: {theme}" if title_hint else theme
            from plan.semantic import extract_semantics as _sem
            from lyrics.translate import (ensure_argos_pair, looks_turkish,
                                          _argos_translate)
            # decompose the theme into many short, concrete queries: split
            # into fragments, translate each, keep 2-6 word noun phrases
            is_tr = looks_turkish([theme])
            can_translate = False
            try:
                can_translate = is_tr and ensure_argos_pair("tr", "en")
            except Exception:
                pass
            fragments = [f.strip() for f in
                         re.split(r"[.,;:\n]", theme) if f.strip()][:14]
            for frag in fragments:
                frag_en = frag
                if can_translate:
                    try:
                        frag_en = _argos_translate(frag, "tr", "en")
                    except Exception:
                        continue
                words = [w for w in re.findall(r"[a-zA-Z']+", frag_en.lower())
                         if w not in ("the", "a", "an", "of", "and", "or",
                                      "in", "on", "to", "is", "are", "that",
                                      "with", "for", "it", "who", "has",
                                      "have", "been", "his", "her", "its")]
                if not 1 <= len(words) <= 7:
                    words = words[:6]
                if len(words) >= 2:
                    q = " ".join(words[:6])
                    if q not in theme_queries:
                        theme_queries.append(q)
            for q in _sem(theme)["queries"][:2]:
                if q not in theme_queries and "abstract light" not in q:
                    theme_queries.append(q)
            theme_queries = theme_queries[:10]
            print(f"[engine] job {self.id} plan: theme queries "
                  f"{theme_queries}", flush=True)
        semantics_fn = None
        try:
            from publish.youtube import Keychain
            api_key = Keychain().get("anthropic_api_key")
            if api_key:
                from plan.semantic import claude_semantics, extract_semantics
                import llm_cache
                texts = sorted({ln["display_text"] for ln in payload["lines"]
                                if ln["display_text"].strip()})
                ck = llm_cache.key_for("sem", title_hint, *texts)
                lut = llm_cache.get_json(ck)
                cached = lut is not None
                if lut is None:
                    lut = claude_semantics(texts, title_hint, api_key)
                    llm_cache.put_json(ck, lut)
                semantics_fn = lambda t: lut.get(t) or extract_semantics(t)
                print(f"[engine] job {self.id} plan: Claude semantics for "
                      f"{len(lut)} line(s)"
                      f"{' (cache, ücretsiz)' if cached else ''}", flush=True)
        except Exception as exc:
            print(f"[engine] job {self.id} plan: LLM semantics unavailable "
                  f"({exc}); using lexicon", flush=True)
        kwargs = {"semantics_fn": semantics_fn} if semantics_fn else {}
        # real singing regions (from align) so lyric scenes over an
        # instrumental section are flagged and their subtitle suppressed
        vocal_segs = []
        try:
            vseg_path = job_dir_for(self.source_job_id) / "vocal_segments.json"
            if vseg_path.exists():
                vocal_segs = [tuple(s) for s in
                              json.loads(vseg_path.read_text(encoding="utf-8"))]
        except Exception:
            vocal_segs = []
        plan = build_scene_plan(payload["lines"], analysis, self.style,
                                seg_start, seg_end, title_hint=title_hint,
                                extra_queries=theme_queries,
                                vocal_segments=vocal_segs, **kwargs)
        plan["source_job_id"] = self.source_job_id
        plan["art_style"] = self.art_style or "storybook"
        self._plan_path().write_text(json.dumps(plan, indent=1),
                                     encoding="utf-8")
        from projects import ProjectStore
        ProjectStore(PROJECTS_DB_PATH).update_settings(
            self.source_job_id, style=plan["style"],
            target_seconds=seg_end - seg_start, segment_start=seg_start)
        print(f"[engine] job {self.id} plan: {plan['scene_count']} scenes, "
              f"style {plan['style']} (recommended {plan['recommended_style']}: "
              f"{plan['recommendation_reason']})", flush=True)
        self.set(state="done", progress=1.0,
                 message=f"Scene plan ready: {plan['scene_count']} scenes "
                         f"({plan['lyric_scene_count']} lyric), "
                         f"style {plan['style']}.",
                 result={
                     "scene_count": plan["scene_count"],
                     "lyric_scene_count": plan["lyric_scene_count"],
                     "style": plan["style"],
                     "recommended_style": plan["recommended_style"],
                     "recommendation_reason": plan["recommendation_reason"],
                 })

    def _run_media(self):
        """Fetch licensed stock media for every scene in the stored plan."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from media.crop import adaptation_plan
        from media.providers import (MediaProviderError, build_providers,
                                     search_all)
        from media.ranking import rank_media
        from media.store import MediaStore, pick_and_fetch

        if self._source_audio() is None:
            return
        plan_path = self._plan_path()
        if not plan_path.exists():
            self.fail("not_found", "Build a scene plan before fetching media.")
            return
        providers = build_providers(self.api_keys)

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        # art style may be changed at media time without a full replan;
        # persist it so the renderer reads the same choice
        if self.art_style:
            plan["art_style"] = self.art_style
        art_style = plan.get("art_style") or "storybook"
        # Comic / Pop-Art is defined by its look — always draw in comic style
        if plan.get("style") == "comicPop":
            art_style = "comic"
        store = MediaStore(MEDIA_DB_PATH)
        for provider, ref in self.exclude_assets:
            store.exclude_asset(self.source_job_id, provider, ref)
            for scene in plan["scenes"]:
                media = scene.get("media")
                if media and media.get("provider") == provider \
                        and str(media.get("provider_ref")) == str(ref):
                    scene["media"] = None
        avoid_refs = set()
        if self.regenerate:
            # remember the outgoing assets so no scene can re-pick any of
            # them this round (rows get replaced as scenes refill)
            for scene in plan["scenes"]:
                media = scene.get("media")
                if media:
                    avoid_refs.add((media["provider"],
                                    str(media["provider_ref"])))
                scene["media"] = None
        dest_dir = MEDIA_CACHE_DIR / self.source_job_id
        scenes = plan["scenes"]
        # Doodle Memory is always AI-drawn. Other (collage) styles use stock
        # photos UNLESS the user asked to draw the background images with AI
        # (ai_images) — then they're generated in the chosen art style too.
        is_doodle = plan.get("style") in FULL_AI_STYLES
        want_ai = is_doodle or self.ai_images
        # a style switch away from AI can leave drawn images in the plan;
        # photo-mode scenes must go back to stock search
        if not want_ai:
            for scene in scenes:
                if is_drawn_media(scene.get("media")):
                    scene["media"] = None
        draw_key = None
        if want_ai:
            try:
                from publish.youtube import Keychain
                draw_key = Keychain().get("fal_api_key")
            except Exception:
                pass
            if not draw_key:
                self.fail("no_api_keys",
                          "AI-drawn images need a fal.ai key in Settings.")
                return
        if not want_ai and not providers:
            self.fail("no_api_keys",
                      "Add at least one stock-provider API key (Pexels "
                      "recommended) in the app's Stock Media Keys section.")
            return
        # collage family shows a rotating pool per scene; give AI scenes the
        # same variety (main + 2 distinct variants). Single-image styles get 1.
        ai_extras = 0 if plan.get("style") in (
            "doodleMemory", "cinemaStill", "comicPop") else 2
        fetched, provider_errors, scene_errors = 0, [], []
        for i, scene in enumerate(scenes):
            if scene.get("media"):
                fetched += 1     # already filled; only empty scenes fetch
                continue
            if draw_key:
                self._check_cancel()
                self.set(state="downloading",
                         progress=0.05 + 0.9 * (i / max(1, len(scenes))),
                         message=f"Drawing scene {i + 1}/{len(scenes)}…")
                try:
                    from media.genai import generate_image
                    from media.crop import adaptation_plan as _ap
                    scene["scene_index"] = scene.get("scene_index", i)
                    cand, data = generate_image(scene, draw_key,
                                                style=art_style)
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    gen_path = dest_dir / f"drawn_{i}.jpg"
                    gen_path.write_bytes(data)
                    store.record_asset(self.source_job_id, i, cand, gen_path)
                    scene["media"] = {**cand.summary(),
                                      "file_path": str(gen_path),
                                      "adaptation": _ap(cand.width,
                                                        cand.height,
                                                        plan["style"])}
                    # rotating pool: distinct variants so collage beat-swaps
                    # cycle different drawings, never the same frame
                    extra_paths = []
                    for k in range(1, ai_extras + 1):
                        try:
                            _c2, d2 = generate_image(scene, draw_key,
                                                     style=art_style, variant=k)
                            ep = dest_dir / f"drawn_{i}_{k}.jpg"
                            ep.write_bytes(d2)
                            extra_paths.append(str(ep))
                        except Exception:
                            break
                    if extra_paths:
                        scene["extra_media"] = extra_paths
                    fetched += 1
                    continue
                except Exception as exc:
                    print(f"[engine] job {self.id} media: drawn scene {i} "
                          f"failed ({exc}); falling back to stock", flush=True)
            self._check_cancel()
            self.set(state="downloading",
                     progress=0.05 + 0.9 * (i / max(1, len(scenes))),
                     message=f"Fetching media for scene {i + 1}/{len(scenes)}…")
            candidates, errors = search_all(providers, scene["queries"],
                                            kind="photo")
            provider_errors.extend(e for e in errors
                                   if e not in provider_errors)
            ranked, rejected = rank_media(candidates, scene,
                                          scene_duration=scene["duration"])
            # let Claude LOOK at the top thumbnails and reorder by fit
            try:
                from publish.youtube import Keychain
                vkey = Keychain().get("anthropic_api_key")
                if vkey and len(ranked) > 1:
                    from media.vision_rank import claude_vision_order
                    theme = self.publish_meta.get("theme", "") or                         plan.get("theme", "")
                    order = claude_vision_order(ranked, scene, theme, vkey)
                    ranked = [ranked[k] for k in order]
                    print(f"[engine] job {self.id} media: scene {i} "
                          f"vision-ranked", flush=True)
            except Exception as exc:
                print(f"[engine] job {self.id} media: vision rank skipped "
                      f"({exc})", flush=True)
            for cand, reason in rejected[:3]:
                print(f"[engine] job {self.id} media: rejected "
                      f"{cand.provider}/{cand.provider_ref}: {reason}",
                      flush=True)
            try:
                chosen, path = pick_and_fetch(
                    ranked, self.source_job_id, i, store, dest_dir,
                    avoid_refs=avoid_refs,
                    log=lambda m: print(f"[engine] job {self.id} media: {m}",
                                        flush=True))
            except MediaProviderError as exc:
                # spec: AI generation is fallback-only, when stock fails —
                # and Cinematic Still is photographs-only, never generated
                fal_key = None
                if plan.get("style") != "cinemaStill":
                    try:
                        from publish.youtube import Keychain
                        fal_key = Keychain().get("fal_api_key")
                    except Exception:
                        pass
                if fal_key:
                    try:
                        from media.genai import generate_image
                        scene["scene_index"] = scene.get("scene_index", i)
                        cand, data = generate_image(scene, fal_key)
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        gen_path = dest_dir / f"gen_{i}.jpg"
                        gen_path.write_bytes(data)
                        store.record_asset(self.source_job_id, i, cand,
                                           gen_path)
                        from media.crop import adaptation_plan as _ap
                        scene["media"] = {**cand.summary(),
                                          "file_path": str(gen_path),
                                          "adaptation": _ap(cand.width,
                                                            cand.height,
                                                            plan["style"])}
                        fetched += 1
                        print(f"[engine] job {self.id} media: scene {i} "
                              f"AI-generated (stock had no match)", flush=True)
                        continue
                    except MediaProviderError as gen_exc:
                        scene_errors.append(f"scene {i}: {exc}; AI fallback: "
                                            f"{gen_exc}")
                        scene["media"] = None
                        continue
                scene_errors.append(f"scene {i}: {exc}")
                scene["media"] = None
                continue
            adaptation = adaptation_plan(chosen.width, chosen.height,
                                         plan["style"])
            scene["media"] = {**chosen.summary(),
                              "file_path": str(path),
                              "adaptation": adaptation}
            # variety pool: 2 more picks per scene so collage extras and
            # beat-swaps never recycle the same few images
            extra_paths = []
            for k in range(2):
                try:
                    _c2, p2 = pick_and_fetch(
                        ranked, self.source_job_id, 1000 + i * 10 + k,
                        store, dest_dir, avoid_refs=avoid_refs)
                    extra_paths.append(str(p2))
                except MediaProviderError:
                    break
            if extra_paths:
                scene["extra_media"] = extra_paths
            fetched += 1

        plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        if fetched == 0:
            detail = "; ".join((provider_errors + scene_errors)[:3])
            self.fail("media_failed", f"No media could be fetched. {detail}")
            return
        message = f"Media ready for {fetched}/{len(scenes)} scenes."
        if scene_errors:
            message += f" {len(scene_errors)} scene(s) had no usable result."
        self.set(state="done", progress=1.0, message=message,
                 result={
                     "fetched_count": fetched,
                     "scene_count": len(scenes),
                     "provider_errors": provider_errors,
                     "scene_errors": scene_errors,
                     "attribution": [s["media"] and {
                         "scene_index": s["scene_index"],
                         "provider": s["media"]["provider"],
                         "creator": s["media"]["creator"],
                         "license": s["media"]["license"],
                         "page_url": s["media"]["page_url"],
                     } for s in scenes],
                 })

    def _words_by_line(self, seg_start):
        """{line_index: words with segment-relative times} from the store."""
        from lyrics.store import LyricsStore
        payload = LyricsStore(LYRICS_DB_PATH).get_lyrics(self.source_job_id)
        words_by_line = {}
        for ln in (payload or {}).get("lines", []):
            words = [{"text": w["text"],
                      "start": None if w["start"] is None
                      else w["start"] - seg_start,
                      "end": None if w["end"] is None
                      else w["end"] - seg_start}
                     for w in ln["words"]]
            words_by_line[ln["line_index"]] = words
        return words_by_line

    def _run_render(self):
        """Render the final styled video from the media-annotated plan."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        sys.path.insert(0, str(Path(__file__).resolve().parent / "render"))

        source_audio = self._source_audio()
        if source_audio is None:
            return
        plan_path = self._plan_path()
        if not plan_path.exists():
            self.fail("not_found", "Build a scene plan (and fetch media) first.")
            return
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        with_media = sum(1 for s in plan["scenes"] if s.get("media"))
        if with_media == 0:
            self.fail("not_found", "Fetch licensed media before rendering.")
            return

        duration = float(plan["segment_end"]) - float(plan["segment_start"])
        VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = (VIDEO_OUTPUT_DIR /
                    f"{self.source_job_id[:8]}_{self.style}_{self.id[:8]}.mp4")

        def report(frac, msg):
            self._check_cancel()
            self.set(progress=0.05 + 0.85 * frac, message=msg)

        self.set(state="analyzing", progress=0.05,
                 message=f"Rendering {self.style}…")
        try:
            if self.style == "doodleMemory":
                from doodle_renderer import render_doodle
                words = self._words_by_line(float(plan["segment_start"]))
                qa_frames = render_doodle(plan, words, source_audio, out_path,
                                          progress=report,
                                          motion_effects=self.motion_effects,
                                          sync_offset=self.sync_offset)
            else:
                from archive_renderer import render_archive
                qa_frames = render_archive(plan, source_audio, out_path,
                                           progress=report,
                                           motion_effects=self.motion_effects,
                                           sync_offset=self.sync_offset)
        except CancelledError:
            out_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            out_path.unlink(missing_ok=True)
            self.fail("render_failed", f"Render failed: {exc}")
            return

        self._check_cancel()
        self.set(state="verifying", progress=0.95, message="Verifying video…")
        out_duration = self._probe_duration(out_path)
        if out_duration is None or abs(out_duration - duration) > 0.5:
            self.fail("ffmpeg_failed", "Rendered video failed verification.")
            return
        from projects import ProjectStore
        ProjectStore(PROJECTS_DB_PATH).record_output(
            self.source_job_id, out_path, style=self.style,
            duration=out_duration)
        self.set(state="done", progress=1.0,
                 message=f"Video ready ({with_media}/{len(plan['scenes'])} "
                         f"scenes with media, {out_duration:.1f}s).",
                 audio_path=str(out_path),
                 audio_duration=out_duration,
                 result={"output_path": str(out_path),
                         "qa_frames": qa_frames,
                         "scene_count": len(plan["scenes"]),
                         "style": self.style})

    def _run_publish_youtube(self):
        """Upload a rendered output via the official YouTube Data API."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from publish.youtube import PublishError, YouTubeConnector

        video = Path(self.url or "")
        try:
            video.resolve().relative_to(VIDEO_OUTPUT_DIR.resolve())
        except ValueError:
            self.fail("invalid_request",
                      "Only rendered videos in Output/videos can be published.")
            return
        if not video.is_file():
            self.fail("not_found", "The rendered video file was not found.")
            return

        def progress(frac):
            self._check_cancel()
            self.set(progress=0.1 + 0.85 * frac,
                     message=f"Uploading to YouTube… {int(frac * 100)}%")

        self.set(state="downloading", progress=0.05,
                 message="Starting YouTube upload…")
        connector = YouTubeConnector()
        meta = self.publish_meta
        try:
            url = connector.publish(
                video, title=meta.get("title") or video.stem,
                description=meta.get("description", ""),
                tags=meta.get("tags", []),
                privacy=meta.get("privacy", "private"),
                progress=progress)
        except PublishError as exc:
            self.fail("publish_failed", str(exc))
            return
        from projects import ProjectStore
        ProjectStore(PROJECTS_DB_PATH).record_publish(
            self.source_job_id or "0" * 32, "youtube", url,
            privacy=meta.get("privacy", "private"))
        self.set(state="done", progress=1.0,
                 message=f"Published to YouTube ({meta.get('privacy', 'private')}).",
                 result={"video_url": url})

    def _run_publish_instagram(self):
        """Publish a rendered output as a Reel via the official Graph API."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from publish.instagram import InstagramConnector
        from publish.youtube import PublishError

        video = Path(self.url or "")
        try:
            video.resolve().relative_to(VIDEO_OUTPUT_DIR.resolve())
        except ValueError:
            self.fail("invalid_request",
                      "Only rendered videos in Output/videos can be published.")
            return
        if not video.is_file():
            self.fail("not_found", "The rendered video file was not found.")
            return

        def progress(frac):
            self._check_cancel()
            self.set(progress=0.1 + 0.8 * frac,
                     message="Instagram is processing the video…")

        self.set(state="downloading", progress=0.05,
                 message="Uploading temporarily and creating the Reel…")
        try:
            url = InstagramConnector().publish(
                video, caption=self.publish_meta.get("description", ""),
                progress=progress)
        except PublishError as exc:
            self.fail("publish_failed", str(exc))
            return
        from projects import ProjectStore
        ProjectStore(PROJECTS_DB_PATH).record_publish(
            self.source_job_id or "0" * 32, "instagram", url)
        self.set(state="done", progress=1.0,
                 message="Published to Instagram.",
                 result={"video_url": url})

    def _run_subprocess(self, cmd):
        """Run a tool with list args (never a shell); poll for cancellation."""
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        while True:
            try:
                out, err = proc.communicate(timeout=0.5)
                return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
            except subprocess.TimeoutExpired:
                if self.cancel_event.is_set():
                    proc.kill()
                    proc.wait()
                    return None


class CancelledError(Exception):
    pass


JOBS = {}
JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Inspection (metadata only, no download)
# --------------------------------------------------------------------------

def ydl_variants(base_opts):
    """Option sets tried in order when YouTube demands sign-in: default,
    iOS player client, then the user's own browser session via yt-dlp's
    official cookies-from-browser (nothing is ever stored in the repo)."""
    yield dict(base_opts)
    v = dict(base_opts)
    v["extractor_args"] = {"youtube": {"player_client": ["ios", "web"]}}
    yield v
    for browser in ("chrome", "safari", "firefox"):
        v = dict(base_opts)
        v["cookiesfrombrowser"] = (browser,)
        yield v


def robust_extract(url, base_opts, download):
    """extract_info with the sign-in fallback chain; raises DownloadError."""
    import yt_dlp
    last = None
    for opts in ydl_variants(base_opts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as exc:
            last = exc
            text = str(exc)
            if not any(m in text for m in ("Sign in to confirm", "cookies",
                                           "Requested format")):
                raise
        except Exception as exc:      # a browser may simply not exist
            last = yt_dlp.utils.DownloadError(str(exc))
    raise last


def inspect_url(url):
    """Fetch metadata for a URL without downloading media."""
    video_id = validate_youtube_url(url)
    if video_id is None:
        return 400, {"valid": False, "error_code": "invalid_url",
                     "message": "Not a valid YouTube URL."}
    import yt_dlp
    ydl_opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "skip_download": True, "socket_timeout": 15}
    try:
        info = robust_extract(url, ydl_opts, download=False)
    except yt_dlp.utils.DownloadError as exc:
        code, human = classify_ytdlp_error(str(exc))
        return 502, {"valid": False, "error_code": code, "message": human}
    return 200, build_metadata(info, url)


# --------------------------------------------------------------------------
# HTTP server (loopback only)
# --------------------------------------------------------------------------

class EngineRequestHandler(BaseHTTPRequestHandler):
    server_version = f"AutoLyricMacEngine/{ENGINE_VERSION}"
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 64 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, HEALTH_PAYLOAD)
            return
        m = re.match(r"^/jobs/([0-9a-f]{32})$", self.path)
        if m:
            with JOBS_LOCK:
                job = JOBS.get(m.group(1))
            if job is None:
                self._send_json(404, {"error_code": "not_found", "message": "Unknown job."})
            else:
                self._send_json(200, job.snapshot())
            return
        m = re.match(r"^/lyrics/([0-9a-f]{32})$", self.path)
        if m:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from lyrics.store import LyricsStore
            payload = LyricsStore(LYRICS_DB_PATH).get_lyrics(m.group(1))
            if payload is None:
                self._send_json(404, {"error_code": "not_found",
                                      "message": "No lyrics stored for this job."})
            else:
                self._send_json(200, payload)
            return
        if self.path == "/instagram/status":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.instagram import InstagramConnector
            self._send_json(200,
                            {"connected": InstagramConnector().is_connected()})
            return
        if self.path.startswith("/youtube/status"):
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.youtube import YouTubeConnector
            query = parse_qs(urlparse(self.path).query)
            state = query.get("state", [None])[0]
            payload = {"connected": YouTubeConnector().is_connected()}
            if state and state in OAUTH_FLOWS:
                payload["flow"] = OAUTH_FLOWS[state]
            self._send_json(200, payload)
            return
        if self.path == "/projects":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from projects import ProjectStore
            projects = ProjectStore(PROJECTS_DB_PATH).list_projects()
            for p in projects:
                job_id = p["job_id"]
                try:
                    job_dir = job_dir_for(job_id)
                except ValueError:
                    continue
                p["audio_exists"] = bool(p.get("audio_path")
                                         and Path(p["audio_path"]).exists()) \
                    or (job_dir / "audio.m4a").exists()
                p["has_plan"] = (job_dir / "scene_plan.json").exists()
            self._send_json(200, {"projects": projects})
            return
        m = re.match(r"^/plan/([0-9a-f]{32})$", self.path)
        if m:
            try:
                plan_path = job_dir_for(m.group(1)) / "scene_plan.json"
            except ValueError:
                plan_path = None
            if plan_path is None or not plan_path.exists():
                self._send_json(404, {"error_code": "not_found",
                                      "message": "No scene plan stored for this job."})
                return
            self._send_json(200, json.loads(plan_path.read_text(encoding="utf-8")))
            return
        self._send_json(404, {"error_code": "not_found", "message": "Unknown endpoint."})

    def do_POST(self):
        if self.path == "/inspect":
            body = self._read_json_body()
            if body is None or "url" not in body:
                self._send_json(400, {"valid": False, "error_code": "invalid_url",
                                      "message": "Request must be JSON with a 'url' field."})
                return
            status, payload = inspect_url(body["url"])
            self._send_json(status, payload)
            return

        if self.path == "/jobs":
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"error_code": "invalid_url",
                                      "message": "Request must be a JSON object."})
                return

            kind = body.get("kind", "download")
            if kind == "publish_instagram":
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                job = Job(kind="publish_instagram",
                          url=str(body.get("output_path") or ""),
                          source_job_id=source_id)
                job.publish_meta = {
                    "description": str(body.get("caption") or "")[:2200]}
            elif kind == "publish_youtube":
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                output_path = str(body.get("output_path") or "")
                privacy = body.get("privacy", "private")
                if privacy not in ("private", "unlisted", "public"):
                    self._send_json(400, {"error_code": "invalid_request",
                                          "message": "privacy must be private, unlisted or public."})
                    return
                job = Job(kind="publish_youtube", url=output_path,
                          source_job_id=source_id)
                job.publish_meta = {
                    "title": str(body.get("title") or "")[:100],
                    "description": str(body.get("description") or "")[:4900],
                    "tags": [str(t)[:60] for t in (body.get("tags") or [])
                             if isinstance(t, str)][:30],
                    "privacy": privacy,
                }
            elif kind == "render":
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                style = body.get("style", "archiveCollage")
                if style not in RENDER_STYLES:
                    self._send_json(400, {"error_code": "invalid_request",
                                          "message": f"Rendering supports {RENDER_STYLES} for now."})
                    return
                job = Job(kind="render", source_job_id=source_id, style=style)
                job.motion_effects = bool(body.get("motion_effects", False))
                try:
                    job.sync_offset = max(-10.0, min(10.0,
                                          float(body.get("sync_offset", 0.0))))
                except (TypeError, ValueError):
                    job.sync_offset = 0.0
            elif kind in ("plan", "media"):
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                if kind == "plan":
                    style = body.get("style", "automatic")
                    if style not in PLAN_STYLES:
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": f"'style' must be one of {PLAN_STYLES}."})
                        return
                    try:
                        target = float(body.get("target_seconds", 0))
                        seg_start = max(0.0, float(body.get("segment_start", 0)))
                    except (TypeError, ValueError):
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "'target_seconds' and 'segment_start' must be numbers."})
                        return
                    if not 5 <= target <= 120:
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "'target_seconds' must be between 5 and 120."})
                        return
                    job = Job(kind="plan", source_job_id=source_id, style=style,
                              target_seconds=target, segment_start=seg_start)
                    job.art_style = _clean_art_style(body.get("art_style"))
                    job.publish_meta = {
                        "theme": str(body.get("theme") or "").strip()[:300]}
                else:
                    raw_keys = body.get("api_keys")
                    if not isinstance(raw_keys, dict):
                        raw_keys = {}
                    api_keys = {name: str(raw_keys[name]).strip()
                                for name in ("pexels", "pixabay", "unsplash")
                                if raw_keys.get(name)
                                and str(raw_keys[name]).strip()}
                    job = Job(kind="media", source_job_id=source_id,
                              api_keys=api_keys)
                    job.art_style = _clean_art_style(body.get("art_style"))
                    job.ai_images = bool(body.get("ai_images"))
                    job.regenerate = bool(body.get("regenerate"))
                    raw_exclude = body.get("exclude") or []
                    if isinstance(raw_exclude, list):
                        job.exclude_assets = [
                            (str(e.get("provider", "")),
                             str(e.get("provider_ref", "")))
                            for e in raw_exclude if isinstance(e, dict)
                            and e.get("provider") and e.get("provider_ref")]
            elif kind in ("lyrics", "align", "translate", "subtitle_preview"):
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                if kind == "translate":
                    job = Job(kind="translate", source_job_id=source_id)
                    job.regenerate = bool(body.get("force"))  # retranslate all
                elif kind == "lyrics":
                    title = str(body.get("title") or "").strip()
                    if not title:
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "A 'title' is required to search lyrics."})
                        return
                    job = Job(kind="lyrics", source_job_id=source_id,
                              artist=str(body.get("artist") or "").strip()[:200],
                              title=title[:200])
                elif kind == "align":
                    job = Job(kind="align", source_job_id=source_id)
                else:
                    style = body.get("style")
                    if style not in SUBTITLE_STYLES:
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": f"'style' must be one of {SUBTITLE_STYLES}."})
                        return
                    try:
                        target = float(body.get("target_seconds", 0))
                        seg_start = max(0.0, float(body.get("segment_start", 0)))
                    except (TypeError, ValueError):
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "'target_seconds' and 'segment_start' must be numbers."})
                        return
                    if not 5 <= target <= 120:
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "'target_seconds' must be between 5 and 120."})
                        return
                    job = Job(kind="subtitle_preview", source_job_id=source_id,
                              style=style, target_seconds=target,
                              segment_start=seg_start)
            elif kind == "analyze":
                source_id = body.get("source_job_id", "")
                if not isinstance(source_id, str) or not JOB_ID_RE.match(source_id):
                    self._send_json(400, {"error_code": "not_found",
                                          "message": "A valid 'source_job_id' is required."})
                    return
                try:
                    target = float(body.get("target_seconds", 0))
                except (TypeError, ValueError):
                    target = 0
                if not 10 <= target <= 120:
                    self._send_json(400, {"error_code": "invalid_request",
                                          "message": "'target_seconds' must be between 10 and 120."})
                    return
                override = body.get("start_override")
                if override is not None:
                    try:
                        override = max(0.0, float(override))
                    except (TypeError, ValueError):
                        self._send_json(400, {"error_code": "invalid_request",
                                              "message": "'start_override' must be a number."})
                        return
                job = Job(kind="analyze", source_job_id=source_id,
                          target_seconds=target, start_override=override)
            elif kind == "download":
                if "url" not in body:
                    self._send_json(400, {"error_code": "invalid_url",
                                          "message": "Request must include a 'url' field."})
                    return
                if body.get("authorized") is not True:
                    self._send_json(403, {"error_code": "not_authorized",
                                          "message": "Authorization acknowledgement is required."})
                    return
                video_id = validate_youtube_url(body["url"])
                if video_id is None:
                    self._send_json(400, {"error_code": "invalid_url",
                                          "message": "Not a valid YouTube URL."})
                    return
                job = Job(url=body["url"], video_id=video_id)
            else:
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": f"Unknown job kind: {kind!r}."})
                return

            with JOBS_LOCK:
                JOBS[job.id] = job
            threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
            self._send_json(202, {"job_id": job.id})
            return

        if self.path == "/youtube/connect":
            body = self._read_json_body() or {}
            client_id = str(body.get("client_id") or "").strip()
            client_secret = str(body.get("client_secret") or "").strip()
            if not client_id or not client_secret:
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": "client_id and client_secret are required."})
                return
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.youtube import build_auth_url, make_pkce
            import secrets as _secrets
            verifier, challenge = make_pkce()
            state = _secrets.token_urlsafe(24)
            OAUTH_FLOWS[state] = {"status": "pending",
                                  "message": "Waiting for authorization…"}
            try:
                start_oauth_listener(client_id, client_secret, verifier, state)
            except OSError as exc:
                self._send_json(500, {"error_code": "oauth_failed",
                                      "message": f"Could not open the local redirect port: {exc}"})
                return
            self._send_json(200, {"auth_url": build_auth_url(client_id,
                                                             challenge, state),
                                  "state": state})
            return

        if self.path == "/instagram/connect":
            body = self._read_json_body() or {}
            token = str(body.get("access_token") or "").strip()
            user_id = str(body.get("ig_user_id") or "").strip()
            s3 = body.get("s3") if isinstance(body.get("s3"), dict) else {}
            if not token or not user_id:
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": "access_token and ig_user_id are required."})
                return
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.instagram import InstagramConnector
            from publish.youtube import PublishError
            try:
                username = InstagramConnector().store_connection(
                    token, user_id, s3)
            except PublishError as exc:
                self._send_json(400, {"error_code": "instagram_failed",
                                      "message": str(exc)})
                return
            self._send_json(200, {"connected": True, "username": username})
            return

        if self.path == "/instagram/disconnect":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.instagram import InstagramConnector
            InstagramConnector().disconnect()
            self._send_json(200, {"connected": False})
            return

        if self.path == "/youtube/disconnect":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from publish.youtube import YouTubeConnector
            YouTubeConnector().disconnect()
            self._send_json(200, {"connected": False})
            return

        if self.path == "/cleanup":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from projects import ProjectStore, run_cleanup
            with JOBS_LOCK:
                active = {j.source_job_id or j.id for j in JOBS.values()}
            count, freed = run_cleanup(REPO_ROOT,
                                       ProjectStore(PROJECTS_DB_PATH), active)
            self._send_json(200, {"removed": count, "freed_bytes": freed})
            return

        m = re.match(r"^/projects/([0-9a-f]{32})/delete$", self.path)
        if m:
            body = self._read_json_body() or {}
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from projects import ProjectStore
            store = ProjectStore(PROJECTS_DB_PATH)
            if not store.delete_project(m.group(1)):
                self._send_json(404, {"error_code": "not_found",
                                      "message": "Unknown project."})
                return
            if body.get("delete_files"):
                try:
                    shutil.rmtree(job_dir_for(m.group(1)), ignore_errors=True)
                    shutil.rmtree(MEDIA_CACHE_DIR / m.group(1),
                                  ignore_errors=True)
                except ValueError:
                    pass
            self._send_json(200, {"deleted": True})
            return

        m = re.match(r"^/lyrics/([0-9a-f]{32})/manual$", self.path)
        if m:
            body = self._read_json_body() or {}
            text = str(body.get("text") or "").strip()
            if len(text) < 10:
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": "Paste at least a few lyric lines."})
                return
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from lyrics.models import LyricsCandidate
            from lyrics.store import LyricsStore
            store = LyricsStore(LYRICS_DB_PATH)
            is_lrc = bool(re.search(r"\[\d{1,3}:\d{2}", text))
            candidate = LyricsCandidate(
                provider="manual",
                artist=str(body.get("artist") or "")[:200],
                title=str(body.get("title") or "")[:200],
                plain_text="" if is_lrc else text[:20000],
                lrc_text=text[:20000] if is_lrc else "")
            store.save_lyrics(m.group(1), candidate, score=1.0)
            payload = store.get_lyrics(m.group(1))
            self._send_json(200, payload)
            return

        m = re.match(r"^/lyrics/([0-9a-f]{32})/translations$", self.path)
        if m:
            body = self._read_json_body() or {}
            text = str(body.get("text") or "")
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from lyrics.store import LyricsStore
            store = LyricsStore(LYRICS_DB_PATH)
            payload = store.get_lyrics(m.group(1))
            if payload is None:
                self._send_json(404, {"error_code": "not_found",
                                      "message": "No lyrics stored for this job."})
                return
            # paste-in-order: i-th pasted line -> i-th lyric line;
            # blank line clears/skips that lyric's translation
            lines = [ln.strip() for ln in text.splitlines()]
            applied = 0
            for i, ln in enumerate(payload["lines"]):
                if i >= len(lines):
                    break
                store.update_line(m.group(1), ln["line_index"],
                                  translation=lines[i])
                if lines[i]:
                    applied += 1
            self._send_json(200, {"applied": applied,
                                  "line_count": len(payload["lines"])})
            return

        m = re.match(r"^/lyrics/([0-9a-f]{32})/line$", self.path)
        if m:
            body = self._read_json_body()
            if body is None or not isinstance(body.get("line_index"), int):
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": "JSON with an integer 'line_index' is required."})
                return
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from lyrics.store import LyricsStore
            store = LyricsStore(LYRICS_DB_PATH)
            kwargs = {}
            if "corrected_text" in body:
                kwargs["corrected_text"] = str(body["corrected_text"] or "")[:500]
            if "translation" in body:
                kwargs["translation"] = str(body["translation"] or "")[:500]
            if not kwargs:
                self._send_json(400, {"error_code": "invalid_request",
                                      "message": "Provide 'corrected_text' and/or 'translation'."})
                return
            if not store.update_line(m.group(1), body["line_index"], **kwargs):
                self._send_json(404, {"error_code": "not_found",
                                      "message": "No such lyric line for this job."})
                return
            payload = store.get_lyrics(m.group(1))
            line = payload["lines"][body["line_index"]]
            self._send_json(200, line)
            return

        m = re.match(r"^/jobs/([0-9a-f]{32})/cancel$", self.path)
        if m:
            with JOBS_LOCK:
                job = JOBS.get(m.group(1))
            if job is None:
                self._send_json(404, {"error_code": "not_found", "message": "Unknown job."})
                return
            job.cancel_event.set()
            self._send_json(202, {"job_id": job.id, "message": "Cancellation requested."})
            return

        self._send_json(404, {"error_code": "not_found", "message": "Unknown endpoint."})

    def log_message(self, fmt, *args):
        print(f"[engine] {self.address_string()} {fmt % args}", flush=True)


def watch_parent(pid):
    """Exit when the parent app dies so no orphan engine lingers."""
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            print(f"[engine] parent pid {pid} gone; shutting down", flush=True)
            os._exit(0)
        time.sleep(2)


def cmd_serve(port, parent_pid=None):
    if parent_pid:
        threading.Thread(target=watch_parent, args=(parent_pid,), daemon=True).start()
    # Loopback only — never bind beyond 127.0.0.1.
    server = ThreadingHTTPServer(("127.0.0.1", port), EngineRequestHandler)
    server.daemon_threads = True
    print(f"AutoLyricMac engine {ENGINE_VERSION} listening on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="AutoLyricMac local engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="print engine health as JSON")
    serve = sub.add_parser("serve", help="run the local HTTP engine server")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--parent-pid", type=int, default=None,
                       help="exit automatically if this process dies")

    args = parser.parse_args()
    if args.command == "health":
        print(json.dumps(HEALTH_PAYLOAD))
    elif args.command == "serve":
        cmd_serve(args.port, args.parent_pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
