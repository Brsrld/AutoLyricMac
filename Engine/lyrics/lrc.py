"""LRC parsing (pure, unit-tested).

Supports standard line tags `[mm:ss.xx]` (several per line), metadata tags
(`[ar:..]`, `[ti:..]`, `[offset:+ms]`, ...), and enhanced per-word tags
`<mm:ss.xx>` inside a line. Everything returns plain data, so parsing is
testable without any provider or model.
"""

import re
from dataclasses import dataclass, field

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[([a-zA-Z#][a-zA-Z]*):(.*)\]$")
_WORD_TAG = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


@dataclass
class LrcWord:
    start: float
    text: str


@dataclass
class LrcLine:
    start: float
    text: str
    words: list[LrcWord] = field(default_factory=list)


def _tag_seconds(minutes, seconds, frac):
    t = int(minutes) * 60 + int(seconds)
    if frac:
        t += int(frac) / (10 ** len(frac))
    return float(t)


def parse_lrc(text):
    """Parse LRC text into (metadata dict, sorted list of LrcLine).

    The `[offset:±ms]` tag is applied to every timestamp (positive offset
    shifts lyrics earlier, per the de-facto LRC convention). Lines that carry
    several time tags are emitted once per tag. Untagged non-empty lines are
    ignored (they are usually credits).
    """
    metadata = {}
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        tags = list(_TIME_TAG.finditer(raw))
        if not tags or tags[0].start() != 0:
            m = _META_TAG.match(raw)
            if m:
                metadata[m.group(1).lower()] = m.group(2).strip()
            continue
        # consume all leading time tags
        end_of_tags = 0
        starts = []
        for tag in tags:
            if tag.start() != end_of_tags:
                break
            starts.append(_tag_seconds(*tag.groups()))
            end_of_tags = tag.end()
        body = raw[end_of_tags:].strip()
        words = _parse_enhanced_words(body)
        clean = _WORD_TAG.sub("", body).strip()
        clean = re.sub(r"\s{2,}", " ", clean)
        for start in starts:
            lines.append(LrcLine(start=start, text=clean, words=list(words)))

    offset_ms = 0
    try:
        offset_ms = int(str(metadata.get("offset", "0")).replace("+", ""))
    except ValueError:
        pass
    if offset_ms:
        shift = -offset_ms / 1000.0
        for line in lines:
            line.start = max(0.0, line.start + shift)
            for w in line.words:
                w.start = max(0.0, w.start + shift)

    lines.sort(key=lambda l: l.start)
    return metadata, lines


def _parse_enhanced_words(body):
    """Extract `<mm:ss.xx>word` pairs from an enhanced-LRC line body."""
    tags = list(_WORD_TAG.finditer(body))
    if not tags:
        return []
    words = []
    for i, tag in enumerate(tags):
        chunk_end = tags[i + 1].start() if i + 1 < len(tags) else len(body)
        chunk = body[tag.end():chunk_end].strip()
        if chunk:
            words.append(LrcWord(start=_tag_seconds(*tag.groups()), text=chunk))
    return words


def infer_line_ends(lines, track_duration=None, max_hold=8.0):
    """Fill in an end time per line: next line's start, capped at `max_hold`.

    Returns a list of (start, end) matching `lines`. The final line ends at
    `track_duration` when known (still capped), else start + max_hold.
    """
    spans = []
    for i, line in enumerate(lines):
        if i + 1 < len(lines):
            end = lines[i + 1].start
        elif track_duration is not None:
            end = track_duration
        else:
            end = line.start + max_hold
        end = max(line.start + 0.5, min(end, line.start + max_hold))
        spans.append((line.start, end))
    return spans


def plain_lines(text):
    """Split plain (unsynchronized) lyrics into non-empty stripped lines."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
