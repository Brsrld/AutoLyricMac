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
    GET  /jobs/<id>             -> job status/progress
    POST /jobs/<id>/cancel      -> request cancellation
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
ENGINE_VERSION = "0.2"

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_JOBS_DIR = REPO_ROOT / "Cache" / "jobs"

# Minimum free disk space required before starting a download.
MIN_FREE_BYTES = 500 * 1024 * 1024

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

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
                 source_job_id=None, target_seconds=None, start_override=None):
        self.id = new_job_id()
        self.kind = kind
        self.url = url
        self.video_id = video_id
        self.source_job_id = source_job_id
        self.target_seconds = target_seconds
        self.start_override = start_override
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
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(self.url, download=True)
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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
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
            if kind == "analyze":
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
