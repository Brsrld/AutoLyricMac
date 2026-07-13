"""Audio analysis and best-segment selection (Phase 2).

`analyze_audio` extracts tempo, beats, onsets, an energy curve, and section
boundaries. `select_segment` is a pure function that scores candidate
windows and returns the best start time plus human-readable reasoning, so it
is directly unit-testable with synthetic data.

Selection criteria (per spec): energy, onset density, section-boundary
alignment, and repetition (chorus likelihood) — with the start snapped to a
beat near a section boundary and fades to avoid clicks. Lyric-completeness
constraints arrive with Phase 3.
"""

import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HOP_SECONDS = 0.5  # resolution of the energy curve used for scoring


# ---------------------------------------------------------------------------
# Feature extraction (needs librosa + ffmpeg)
# ---------------------------------------------------------------------------

def decode_to_wav(src, ffmpeg, sr=22050):
    """Decode any audio file to mono wav for analysis."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src),
                    "-ac", "1", "-ar", str(sr), tmp.name], check=True)
    return Path(tmp.name)


def analyze_audio(audio_path, ffmpeg, progress=None):
    """Full analysis dict for an audio file."""
    import librosa
    import numpy as np

    def report(frac, msg):
        if progress:
            progress(frac, msg)

    report(0.05, "Decoding audio for analysis…")
    wav = decode_to_wav(audio_path, ffmpeg)
    try:
        report(0.15, "Loading waveform…")
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
        duration = float(len(y) / sr)

        report(0.35, "Detecting tempo and beats…")
        # short/sparse audio (e.g. mostly speech or silence) can break the
        # music-oriented detectors; degrade gracefully instead of failing
        try:
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        except Exception:
            tempo, beats = 100.0, []

        report(0.55, "Detecting onsets and energy…")
        try:
            onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time").tolist()
        except Exception:
            onsets = []
        hop = int(sr * HOP_SECONDS)
        rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
        rms = rms / (rms.max() or 1.0)

        report(0.75, "Finding section boundaries…")
        # spectral-novelty section estimate via agglomerative segmentation
        try:
            n_sections = max(4, min(12, int(duration / 30)))
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            bounds = librosa.segment.agglomerative(chroma, k=n_sections)
            section_times = librosa.frames_to_time(bounds, sr=sr).tolist()

            # repetition proxy: self-similarity of chroma (chorus-ish)
            report(0.9, "Estimating repetition…")
            rec = librosa.segment.recurrence_matrix(
                librosa.util.sync(chroma, bounds), mode="affinity", sym=True)
            section_repetition = rec.sum(axis=0).tolist()
        except Exception:
            section_times = [0.0, duration / 2]
            section_repetition = [0.5, 0.5]

        return {
            "duration": duration,
            "tempo_bpm": float(np.atleast_1d(tempo)[0]),
            "beats": beats,
            "onsets": onsets,
            "energy_hop_seconds": HOP_SECONDS,
            "energy": rms.tolist(),
            "sections": section_times,
            "section_repetition": section_repetition,
        }
    finally:
        wav.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Segment selection (pure, unit-tested)
# ---------------------------------------------------------------------------

@dataclass
class SegmentChoice:
    start: float
    end: float
    score: float
    reasons: list = field(default_factory=list)


def _window_stats(analysis, start, length):
    hop = analysis["energy_hop_seconds"]
    energy = analysis["energy"]
    i0 = int(start / hop)
    i1 = min(int((start + length) / hop) + 1, len(energy))
    window = energy[i0:i1] or [0.0]
    mean_energy = sum(window) / len(window)
    onset_count = sum(1 for t in analysis["onsets"] if start <= t < start + length)
    onset_density = onset_count / length
    return mean_energy, onset_density


def _nearest(values, t):
    if not values:
        return None
    return min(values, key=lambda v: abs(v - t))


def select_segment(analysis, target_seconds, start_override=None):
    """Pick the best window of `target_seconds`, or honor an override.

    Returns a SegmentChoice with human-readable reasoning. Deterministic.
    """
    duration = analysis["duration"]
    target = float(target_seconds)
    if duration <= target:
        return SegmentChoice(0.0, duration, 1.0,
                             [f"Track ({duration:.1f}s) is not longer than the "
                              f"requested {target:.0f}s — using the whole track."])

    if start_override is not None:
        start = max(0.0, min(float(start_override), duration - target))
        snapped = _nearest(analysis.get("beats", []), start)
        reasons = [f"Manual start override at {start:.1f}s."]
        if snapped is not None and abs(snapped - start) <= 0.35 and snapped <= duration - target:
            reasons.append(f"Snapped to the nearest beat at {snapped:.2f}s to avoid a mid-beat click.")
            start = snapped
        return SegmentChoice(start, start + target, 1.0, reasons)

    # candidates: every section boundary + a coarse grid, snapped to beats
    candidates = set()
    for t in analysis.get("sections", []):
        if t <= duration - target:
            candidates.add(round(t, 2))
    grid = 5.0
    t = 0.0
    while t <= duration - target:
        candidates.add(round(t, 2))
        t += grid

    max_onset_density = max(
        (_window_stats(analysis, c, target)[1] for c in candidates), default=1.0) or 1.0

    sections = analysis.get("sections", [])
    repetition = analysis.get("section_repetition", [])

    best = None
    for cand in sorted(candidates):
        snapped = _nearest(analysis.get("beats", []), cand)
        start = snapped if (snapped is not None
                            and abs(snapped - cand) <= 0.5
                            and snapped <= duration - target) else cand
        mean_energy, onset_density = _window_stats(analysis, start, target)

        # section-boundary alignment (starting on a musical boundary)
        nearest_bound = _nearest(sections, start)
        bound_dist = abs(nearest_bound - start) if nearest_bound is not None else 99.0
        boundary_score = max(0.0, 1.0 - bound_dist / 4.0)

        # repetition (chorus likelihood) of the section this window starts in
        rep_score = 0.0
        if sections and repetition:
            sec_idx = max(0, sum(1 for s in sections if s <= start) - 1)
            rep = repetition[min(sec_idx, len(repetition) - 1)]
            rep_max = max(repetition) or 1.0
            rep_score = rep / rep_max

        score = (0.40 * mean_energy
                 + 0.25 * (onset_density / max_onset_density)
                 + 0.20 * boundary_score
                 + 0.15 * rep_score)

        if best is None or score > best[0]:
            best = (score, start, mean_energy, onset_density, boundary_score, rep_score)

    score, start, mean_energy, onset_density, boundary_score, rep_score = best
    reasons = [
        f"Chose {start:.1f}s–{start + target:.1f}s of {duration:.1f}s "
        f"(score {score:.3f}).",
        f"Mean energy {mean_energy:.2f} (40% weight), onset density "
        f"{onset_density:.2f}/s (25%), section-boundary alignment "
        f"{boundary_score:.2f} (20%), repetition/chorus likelihood "
        f"{rep_score:.2f} (15%).",
        "Start snapped to a beat to avoid clicks; 0.4s fades applied at cut.",
    ]
    return SegmentChoice(round(start, 3), round(start + target, 3), score, reasons)


def cut_segment(src, dest, choice, ffmpeg, fade=0.4):
    """Cut [start, end) from src with fades; AAC/M4A output."""
    length = choice.end - choice.start
    fade_out_start = max(length - fade, 0)
    cmd = [ffmpeg, "-y", "-v", "error",
           "-ss", f"{choice.start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
           "-af", f"afade=t=in:d={fade},afade=t=out:st={fade_out_start:.3f}:d={fade}",
           "-c:a", "aac", "-b:a", "192k", str(dest)]
    return subprocess.run(cmd, capture_output=True, text=True)
