"""Word-level lyric alignment (Phase 3).

Two halves:

1. `transcribe_words` — thin wrapper around mlx-whisper (Apple Silicon) that
   returns recognized words with timestamps and probabilities. Imported
   lazily so everything else works without the model installed.
2. Pure alignment mapping — matches canonical lyric tokens against the
   recognized token stream (difflib anchor blocks), interpolates timing for
   unmatched words between anchors, and produces per-word and per-line
   confidence. Fully unit-testable with synthetic ASR output.

Confidence: matched words inherit the ASR probability; interpolated words get
a low fixed confidence so uncertainty is always visible downstream.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_MODEL = "mlx-community/whisper-base-mlx"
INTERPOLATED_CONFIDENCE = 0.2
MIN_WORD_DURATION = 0.08


# ---------------------------------------------------------------------------
# Transcription (needs mlx-whisper + model weights)
# ---------------------------------------------------------------------------

def _decode_pcm(audio_path, ffmpeg, sr=16000):
    """Decode to 16 kHz mono float32 with an explicit ffmpeg path.

    mlx-whisper's own loader shells out to a bare `ffmpeg`, which is not on
    PATH when the app launches the engine — so we decode ourselves.
    """
    import subprocess

    import numpy as np
    out = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(audio_path),
         "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True, check=True)
    return np.frombuffer(out.stdout, dtype=np.float32)


def transcribe_words(audio_path, model=DEFAULT_MODEL, language=None,
                     ffmpeg="ffmpeg"):
    """Recognized words + detected language.

    Returns ([{"text", "start", "end", "prob"}], language_code).
    """
    import mlx_whisper  # lazy: only the align job needs it

    audio = _decode_pcm(audio_path, ffmpeg)
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model,
        word_timestamps=True, language=language, fp16=True)
    words = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            words.append({
                "text": text,
                "start": float(w["start"]),
                "end": float(w["end"]),
                "prob": float(w.get("probability", 1.0)),
            })
    return words, result.get("language") or language or "en"


# ---------------------------------------------------------------------------
# Pure alignment mapping
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w']+")


def normalize_token(token):
    """Fold case/accents/punctuation so 'Hold,' matches 'hold'."""
    t = unicodedata.normalize("NFKD", token or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _PUNCT.sub("", t.lower().replace("’", "'"))
    return t.replace("'", "")


@dataclass
class TokenRef:
    line_index: int
    word_index: int
    raw: str
    norm: str


def tokenize_lines(line_texts):
    """Flatten lyric lines into an ordered token list (empty tokens dropped)."""
    tokens = []
    for li, text in enumerate(line_texts):
        wi = 0
        for raw in text.split():
            norm = normalize_token(raw)
            if not norm:
                continue
            tokens.append(TokenRef(li, wi, raw, norm))
            wi += 1
    return tokens


def align_tokens(lyric_tokens, asr_words):
    """Map lyric tokens onto ASR word timings.

    Returns a list (parallel to `lyric_tokens`) of dicts:
    {"start", "end", "confidence", "matched"} — every token gets timing
    (matched directly or interpolated between the nearest anchors); tokens
    outside any anchor pair get None timing and zero confidence.
    """
    lyric_norm = [t.norm for t in lyric_tokens]
    asr_norm = [normalize_token(w["text"]) for w in asr_words]

    matcher = SequenceMatcher(None, lyric_norm, asr_norm, autojunk=False)
    result = [{"start": None, "end": None, "confidence": 0.0, "matched": False}
              for _ in lyric_tokens]

    anchors = []  # (lyric_idx, asr_idx)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            li, ai = block.a + k, block.b + k
            w = asr_words[ai]
            result[li] = {"start": w["start"], "end": w["end"],
                          "confidence": w.get("prob", 1.0), "matched": True}
            anchors.append((li, ai))

    # interpolate unmatched lyric tokens between surrounding anchors
    for gap_start, gap_end in _gaps(anchors, len(lyric_tokens)):
        left = result[gap_start - 1] if gap_start > 0 else None
        right = result[gap_end] if gap_end < len(lyric_tokens) else None
        if left is None or right is None:
            continue  # leading/trailing gap: no timing evidence at all
        t0, t1 = left["end"], right["start"]
        if t1 <= t0:
            t1 = t0 + MIN_WORD_DURATION * (gap_end - gap_start)
        n = gap_end - gap_start
        span = (t1 - t0) / n
        for k, idx in enumerate(range(gap_start, gap_end)):
            start = t0 + k * span
            result[idx] = {"start": start,
                           "end": max(start + MIN_WORD_DURATION, t0 + (k + 1) * span),
                           "confidence": INTERPOLATED_CONFIDENCE,
                           "matched": False}
    return result


def _gaps(anchors, total):
    """Yield (start, end) index ranges of unmatched runs between anchors."""
    matched = sorted(a[0] for a in anchors)
    gaps = []
    prev = -1
    for m in matched + [total]:
        if m > prev + 1:
            gaps.append((prev + 1, m))
        prev = m
    return gaps


def align_lyrics(line_texts, asr_words):
    """Align lyric lines to ASR words.

    Returns (aligned_lines, matched_ratio, mean_confidence) where each
    aligned line is {"line_index", "start", "end", "confidence", "words"}.
    Lines with no timing evidence keep start/end None and confidence 0 —
    callers must surface those as uncertain, never display them silently.
    """
    tokens = tokenize_lines(line_texts)
    mapped = align_tokens(tokens, asr_words)

    aligned = []
    for li, text in enumerate(line_texts):
        refs = [(t, m) for t, m in zip(tokens, mapped) if t.line_index == li]
        words = [{"text": t.raw, "start": m["start"], "end": m["end"],
                  "confidence": round(m["confidence"], 3)} for t, m in refs]
        timed = [m for _, m in refs if m["start"] is not None]
        if timed:
            start = min(m["start"] for m in timed)
            end = max(m["end"] for m in timed)
            confidence = sum(m["confidence"] for _, m in refs) / len(refs)
        else:
            start = end = None
            confidence = 0.0
        aligned.append({"line_index": li, "start": start, "end": end,
                        "confidence": round(confidence, 3), "words": words})

    if tokens:
        matched_ratio = sum(1 for m in mapped if m["matched"]) / len(tokens)
        mean_confidence = sum(m["confidence"] for m in mapped) / len(tokens)
    else:
        matched_ratio = mean_confidence = 0.0
    return aligned, round(matched_ratio, 4), round(mean_confidence, 4)
