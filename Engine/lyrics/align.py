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

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
FALLBACK_MODEL = "mlx-community/whisper-base-mlx"
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


def align_lyrics_monotonic(line_texts, asr_words, min_ratio=0.45):
    """Line-by-line forward alignment for repetitive lyrics.

    A moving cursor guarantees monotonic timing: each line searches only
    forward in the ASR stream for its best-matching window, so repeated
    lines ("bülbül bülbül...") bind to successive occurrences instead of
    all collapsing onto the first one. Unmatched lines stay untimed (the
    LRC fallback can still rescue them).
    """
    asr_norm = [normalize_token(w["text"]) for w in asr_words]
    aligned = []
    cursor = 0
    total_conf = matched_lines = 0.0
    for li, text in enumerate(line_texts):
        tokens = [t for t in (normalize_token(w) for w in text.split()) if t]
        raws = [w for w in text.split() if normalize_token(w)]
        best = (0.0, None)
        if tokens and cursor < len(asr_words):
            wlen = len(tokens)
            for j in range(cursor, min(len(asr_words),
                                       cursor + 400) - max(1, wlen) + 1):
                window = asr_norm[j:j + wlen]
                m = SequenceMatcher(None, tokens, window,
                                    autojunk=False).ratio()
                if m > best[0]:
                    best = (m, j)
                if m >= 0.72:
                    best = (m, j)   # greedy: earliest good match wins
                    break
        words = []
        if best[1] is not None and best[0] >= min_ratio:
            j = best[1]
            span = asr_words[j:j + len(tokens)]
            start = span[0]["start"]
            end = max(w["end"] for w in span)
            end = max(end, start + 0.5)
            n = len(raws)
            for k, raw in enumerate(raws):
                w = span[min(k, len(span) - 1)]
                words.append({"text": raw, "start": w["start"],
                              "end": w["end"], "confidence": round(best[0], 3)})
            aligned.append({"line_index": li, "start": start, "end": end,
                            "confidence": round(best[0], 3), "words": words})
            cursor = j + len(span)
            total_conf += best[0]
            matched_lines += 1
        else:
            aligned.append({"line_index": li, "start": None, "end": None,
                            "confidence": 0.0,
                            "words": [{"text": r, "start": None, "end": None,
                                       "confidence": 0.0} for r in raws]})
    n = max(1, len(line_texts))
    return aligned, round(matched_lines / n, 4), round(total_conf / n, 4)


def words_to_lines(words, gap=0.9, max_words=8):
    """Group ASR words into lyric lines on pauses (pure)."""
    lines, cur = [], []
    for i, w in enumerate(words):
        if cur and (w["start"] - words[i - 1]["end"] > gap
                    or len(cur) >= max_words):
            lines.append(" ".join(x["text"] for x in cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(" ".join(x["text"] for x in cur))
    return lines


LRC_FALLBACK_CONFIDENCE = 0.6


def is_monotonic(aligned, tol=0.05):
    """True if timed line starts never move backward (a sane timeline).

    A scrambled hybrid (a few wrong ASR matches mixed with clean LRC
    timings) shows up here as backward jumps.
    """
    last = None
    for line in aligned:
        s = line.get("start")
        if s is None:
            continue
        if last is not None and s < last - tol:
            return False
        last = s
    return True


def align_from_lrc(line_texts, seed_spans, confidence=0.6):
    """Build the whole timeline straight from synced-LRC spans.

    A provider's synced LRC is a monotonic, human-checked ground truth.
    When ASR alignment is weak or scrambled we trust it wholesale instead
    of a corrupted ASR/LRC mix: each line takes its LRC span, words spread
    evenly. Lines without a span stay untimed. Returns
    (aligned, coverage_ratio, mean_confidence).
    """
    aligned = []
    timed = 0
    for li, text in enumerate(line_texts):
        raws = [w for w in text.split() if normalize_token(w)]
        seed = seed_spans.get(li)
        if seed and seed[0] is not None:
            start = float(seed[0])
            end = float(seed[1] if seed[1] is not None else start + 3.0)
            end = max(end, start + 0.8)
            words = []
            n = max(1, len(raws))
            step = (end - start) / n
            for k, raw in enumerate(raws):
                words.append({"text": raw,
                              "start": round(start + k * step, 3),
                              "end": round(start + (k + 1) * step, 3),
                              "confidence": confidence})
            aligned.append({"line_index": li, "start": round(start, 3),
                            "end": round(end, 3), "confidence": confidence,
                            "words": words})
            timed += 1
        else:
            aligned.append({"line_index": li, "start": None, "end": None,
                            "confidence": 0.0,
                            "words": [{"text": r, "start": None, "end": None,
                                       "confidence": 0.0} for r in raws]})
    n = max(1, len(line_texts))
    return aligned, round(timed / n, 4), round(confidence * timed / n, 4)


def merge_lrc_fallback(aligned, seed_spans):
    """Hybrid alignment: where ASR failed, trust provider LRC timings.

    `seed_spans` maps line_index -> (start, end) from synchronized lyrics.
    Lines with low/no ASR confidence but a provider timestamp get that
    timing (words spread evenly) at LRC_FALLBACK_CONFIDENCE — visibly less
    certain than a real match, but never silently blank. Returns the count
    of rescued lines; mutates `aligned` in place.
    """
    rescued = 0
    for line in aligned:
        seed = seed_spans.get(line["line_index"])
        if seed is None or seed[0] is None:
            continue
        if line["confidence"] >= 0.45 and line["start"] is not None:
            continue
        start, end = float(seed[0]), float(seed[1] or seed[0] + 3.0)
        end = max(end, start + 0.8)
        line["start"], line["end"] = start, end
        line["confidence"] = LRC_FALLBACK_CONFIDENCE
        words = line.get("words") or []
        if words:
            step = (end - start) / len(words)
            for k, w in enumerate(words):
                w["start"] = round(start + k * step, 3)
                w["end"] = round(start + (k + 1) * step, 3)
                w["confidence"] = LRC_FALLBACK_CONFIDENCE
        rescued += 1
    return rescued
