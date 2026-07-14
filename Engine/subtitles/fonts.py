"""Script-aware font selection and complex-text shaping for subtitles.

The default subtitle fonts (American Typewriter, Bradley Hand) cover Latin
and Turkish but have no glyphs for Arabic/Hebrew — those render as empty
"tofu" boxes. This module detects such scripts per line, swaps to a font
that covers them, and (because this Pillow build lacks libraqm) shapes
Arabic with `arabic_reshaper` + `python-bidi` so the letters join and read
right-to-left. All helpers degrade gracefully if a font or lib is missing.
"""

# macOS system fonts with full coverage for right-to-left scripts.
FONT_ARABIC = "/System/Library/Fonts/SFArabic.ttf"
FONT_ARABIC_FALLBACK = "/System/Library/Fonts/Supplemental/GeezaPro.ttc"
FONT_HEBREW = "/System/Library/Fonts/Supplemental/Arial Hebrew.ttf"


def _in(ch, lo, hi):
    return lo <= ch <= hi


def has_arabic(text):
    """True if any character is in an Arabic Unicode block."""
    return any(_in(c, "؀", "ۿ") or _in(c, "ݐ", "ݿ")
               or _in(c, "ࢠ", "ࣿ") or _in(c, "ﭐ", "﷿")
               or _in(c, "ﹰ", "﻿") for c in text or "")


def has_hebrew(text):
    return any(_in(c, "֐", "׿") for c in text or "")


def is_rtl(text):
    return has_arabic(text) or has_hebrew(text)


def _first_existing(*paths):
    from pathlib import Path
    for p in paths:
        if p and Path(p).exists():
            return p
    return None


def font_for(text, latin_font):
    """Font path that can render `text`; falls back to `latin_font`."""
    if has_arabic(text):
        return _first_existing(FONT_ARABIC, FONT_ARABIC_FALLBACK) or latin_font
    if has_hebrew(text):
        return _first_existing(FONT_HEBREW) or latin_font
    return latin_font


def shape(text):
    """Return `text` ready for a non-shaping renderer.

    For Arabic, reshape to positional glyph forms and apply the bidi
    algorithm so a left-to-right renderer draws it correctly. Latin text
    (and any failure) passes through unchanged.
    """
    if not text:
        return text
    if has_arabic(text) or has_hebrew(text):
        try:
            from bidi.algorithm import get_display
            reshaped = text
            if has_arabic(text):
                import arabic_reshaper
                reshaped = arabic_reshaper.reshape(text)
            return get_display(reshaped)
        except Exception:
            return text
    return text
