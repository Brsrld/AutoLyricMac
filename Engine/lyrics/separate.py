"""Vocal separation for precise lyric alignment (Demucs, local).

Aligning against isolated vocals removes the instruments that blur
Whisper's word timestamps. The separated track is cached per job as
`vocals.wav`; any failure falls back to the full mix upstream.
"""

import subprocess
import sys
from pathlib import Path


def separate_vocals(audio_path, log=None):
    """Return the path to the isolated-vocals wav (cached), or None."""
    audio_path = Path(audio_path)
    cached = audio_path.parent / "vocals.wav"
    if cached.exists():
        return cached
    out_dir = audio_path.parent / "demucs_tmp"
    cmd = [sys.executable, "-m", "demucs", "--two-stems", "vocals",
           "-n", "htdemucs", "-o", str(out_dir), str(audio_path)]
    if log:
        log("Separating vocals (Demucs)…")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=1800)
        if result.returncode != 0:
            if log:
                log(f"Demucs failed: {(result.stderr or '')[-200:]}")
            return None
        produced = list(out_dir.rglob("vocals.wav"))
        if not produced:
            return None
        produced[0].replace(cached)
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
        return cached
    except Exception as exc:
        if log:
            log(f"Demucs unavailable: {exc}")
        return None
