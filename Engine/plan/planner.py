"""Deterministic scene planner (Phase 4).

Turns aligned lyric lines + Phase 2 audio analysis into a structured scene
plan. Main scenes follow lyric phrases (never every beat); beats only feed
micro-motion pulses; higher energy shortens scenes and strengthens movement.
Everything is pure and seeded, so the same inputs always produce the same
plan (an optional LLM provider may later enrich `meaning`/`queries` behind
the same semantics interface).
"""

import random

from .semantic import dominant_emotion, extract_semantics

# style -> (min, max) scene seconds by energy band, per Docs/STYLE_GUIDE.md
_DURATIONS = {
    "archiveCollage": {"calm": (4.0, 7.0), "normal": (3.0, 5.0),
                       "energetic": (2.0, 4.0)},
    "doodleMemory": {"calm": (3.5, 5.5), "normal": (3.0, 5.0),
                     "energetic": (2.5, 4.0)},
}

_MOTIONS = {
    "archiveCollage": ["slow_push", "slow_pull", "gentle_drift",
                       "subtle_rotate", "layer_reposition"],
    "doodleMemory": ["breathe", "slide_in", "gentle_drift", "micro_bounce"],
}

_TRANSITIONS = {
    "archiveCollage": [("crossfade", 0.5), ("fade_white", 0.4),
                       ("fade_dark", 0.45), ("block_wipe", 0.35),
                       ("layered_dissolve", 0.6)],
    "doodleMemory": [("cut", 0.0), ("short_dissolve", 0.25),
                     ("paper_wipe", 0.3), ("sticker_pop", 0.2)],
}

_OVERLAYS = {
    "archiveCollage": ["grain", "vignette"],
    "doodleMemory": ["warm_grain"],
}

_BANDS = ("lower", "center", "lower", "upper")

MAX_AMBIENT_SCENE = 6.0     # instrumental gaps split into scenes this long
MIN_LYRIC_GAP = 3.0         # smaller gaps just extend the previous scene


def _mean_energy(analysis, start, end):
    hop = analysis.get("energy_hop_seconds", 0.5)
    energy = analysis.get("energy") or []
    i0, i1 = int(start / hop), max(int(start / hop) + 1, int(end / hop))
    window = energy[i0:i1]
    return sum(window) / len(window) if window else 0.5


def _energy_band(value):
    if value < 0.40:
        return "calm"
    if value < 0.70:
        return "normal"
    return "energetic"


def _beats_in(analysis, start, end):
    return [round(b - start, 3) for b in analysis.get("beats", [])
            if start <= b < end]


def recommend_style(emotion_totals, tempo_bpm):
    """Automatic preset choice per the style guide, with reasoning."""
    archive = (emotion_totals.get("melancholy", 0)
               + emotion_totals.get("loneliness", 0)
               + emotion_totals.get("longing", 0)
               + 0.5 * emotion_totals.get("nostalgia", 0))
    doodle = (emotion_totals.get("love", 0) + emotion_totals.get("joy", 0)
              + emotion_totals.get("calm", 0) + emotion_totals.get("hope", 0)
              + 0.5 * emotion_totals.get("nostalgia", 0))
    total = archive + doodle
    if total <= 0:
        return "archiveCollage", 0.0, "no emotional signal; defaulting to Archive Collage"
    if doodle > archive * 1.15:
        conf = doodle / total
        return "doodleMemory", round(conf, 3), \
            f"warm/domestic emotions dominate ({doodle:.1f} vs {archive:.1f})"
    conf = archive / total
    return "archiveCollage", round(conf, 3), \
        f"melancholic/longing emotions lead ({archive:.1f} vs {doodle:.1f})"


def build_scene_plan(lines, analysis, style, segment_start, segment_end,
                     semantics_fn=extract_semantics):
    """Build the structured scene plan for a segment.

    `lines`: lyric dicts with absolute start/end (only timed lines are used):
    {display_text, translation, start, end, confidence, uncertain}.
    Returns {"style", "recommended_style", "scenes": [...], ...}.
    """
    seg_len = segment_end - segment_start
    timed = sorted((ln for ln in lines
                    if ln.get("start") is not None and ln.get("end") is not None
                    and ln["end"] > segment_start and ln["start"] < segment_end),
                   key=lambda ln: ln["start"])

    # --- carve the segment into phrase-driven spans -----------------------
    spans = []      # (start, end, line_or_None)
    cursor = segment_start
    for ln in timed:
        start = max(segment_start, ln["start"])
        end = min(segment_end, ln["end"])
        if start - cursor >= MIN_LYRIC_GAP:
            _append_ambient(spans, cursor, start)
        elif spans and start > cursor:
            s0, e0, l0 = spans[-1]
            spans[-1] = (s0, start, l0)      # extend previous scene to here
        elif start > cursor and not spans:
            start = cursor                    # lead-in belongs to first scene
        spans.append((start, max(end, start + 0.5), ln))
        cursor = spans[-1][1]
    if segment_end - cursor >= MIN_LYRIC_GAP:
        _append_ambient(spans, cursor, segment_end)
    elif spans:
        s0, e0, l0 = spans[-1]
        spans[-1] = (s0, segment_end, l0)
    else:
        _append_ambient(spans, segment_start, segment_end)

    # --- decide the style first (semantics pass), so "automatic" gets the
    # recommended preset's timing rules, not a fallback's -------------------
    emotion_totals = {}
    for ln in timed:
        for k, v in semantics_fn(ln["display_text"])["emotions"].items():
            emotion_totals[k] = emotion_totals.get(k, 0.0) + v
    rec_style, rec_conf, rec_reason = recommend_style(
        emotion_totals, analysis.get("tempo_bpm", 100.0))
    style_key = style if style in _DURATIONS else rec_style

    # --- build scenes -------------------------------------------------------
    scenes = []
    rng = random.Random(int(segment_start * 10) + len(spans))
    for i, (start, end, ln) in enumerate(spans):
        text = ln["display_text"] if ln else ""
        sem = semantics_fn(text) if text else semantics_fn("")
        energy = _mean_energy(analysis, start, end)
        band = _energy_band(energy)
        lo, hi = _DURATIONS[style_key][band]
        emotion = dominant_emotion(sem["emotions"])

        motions = _MOTIONS[style_key]
        motion = motions[(i + int(energy * 10)) % len(motions)]
        trans_name, trans_dur = _TRANSITIONS[style_key][
            rng.randrange(len(_TRANSITIONS[style_key]))]
        if band == "energetic":
            trans_dur = round(trans_dur * 0.7, 3)

        overlays = list(_OVERLAYS[style_key])
        if style_key == "archiveCollage" and i % 3 == 2:
            overlays.append("dust_flicker")

        subjects = sem["subjects"] or (["texture"] if not text else [])
        meaning = (f"{emotion} moment about {', '.join(subjects[:3])}"
                   if subjects else f"{emotion} instrumental passage")

        scenes.append({
            "scene_index": i,
            "start": round(start - segment_start, 3),
            "end": round(end - segment_start, 3),
            "duration": round(end - start, 3),
            "target_duration": [lo, hi],
            "lyric": text or None,
            "translation": (ln or {}).get("translation"),
            "uncertain": bool((ln or {}).get("uncertain")),
            "meaning": meaning,
            "emotion": emotion,
            "energy": round(energy, 3),
            "energy_band": band,
            "subjects": subjects,
            "queries": sem["queries"],
            "media_preference": _media_preference(style_key, band),
            "motion": {
                "type": motion,
                "amount": round(0.03 + 0.05 * energy, 3),
                "pulse_beats": _beats_in(analysis, start, end),
            },
            "transition": {"type": trans_name, "duration": trans_dur},
            "overlays": overlays,
            "subtitle": {"band": _BANDS[i % len(_BANDS)], "seed": i},
        })

    return {
        "style": style_key,
        "recommended_style": rec_style,
        "recommendation_confidence": rec_conf,
        "recommendation_reason": rec_reason,
        "segment_start": segment_start,
        "segment_end": segment_end,
        "scene_count": len(scenes),
        "lyric_scene_count": sum(1 for s in scenes if s["lyric"]),
        "scenes": scenes,
    }


def _append_ambient(spans, start, end):
    """Split an instrumental gap into ambient scenes of sane length."""
    length = end - start
    parts = max(1, round(length / MAX_AMBIENT_SCENE + 0.4))
    step = length / parts
    for k in range(parts):
        spans.append((start + k * step, start + (k + 1) * step, None))


def _media_preference(style, band):
    if style == "doodleMemory":
        return "video" if band == "energetic" else "photo"
    return "photo"
