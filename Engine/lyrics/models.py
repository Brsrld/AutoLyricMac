"""Shared lyric data types (Phase 3).

A `LyricsCandidate` is what a provider returns from a search; ranking picks
one, and the store persists it as canonical lyrics with per-line/per-word
timing and confidence added by alignment.
"""

from dataclasses import dataclass, field


@dataclass
class LyricsCandidate:
    """One search result from a lyrics provider."""
    provider: str
    provider_ref: str = ""
    artist: str = ""
    title: str = ""
    album: str = ""
    duration: float | None = None      # seconds, if the provider knows it
    plain_text: str = ""               # canonical plain lyrics
    lrc_text: str = ""                 # synchronized LRC source, if any
    instrumental: bool = False

    @property
    def synced(self) -> bool:
        return bool(self.lrc_text.strip())

    def summary(self) -> dict:
        return {
            "provider": self.provider,
            "provider_ref": self.provider_ref,
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "duration": self.duration,
            "synced": self.synced,
            "instrumental": self.instrumental,
        }


@dataclass
class LyricWord:
    """One word with (possibly aligned) timing and confidence."""
    text: str
    start: float | None = None
    end: float | None = None
    confidence: float | None = None    # 0..1; None = never aligned


@dataclass
class LyricLine:
    """One lyric line; timings are in full-track seconds."""
    index: int
    text: str                          # canonical provider text
    start: float | None = None
    end: float | None = None
    confidence: float | None = None
    corrected_text: str | None = None  # user correction, None if untouched
    translation: str | None = None     # optional Turkish translation
    words: list[LyricWord] = field(default_factory=list)

    @property
    def display_text(self) -> str:
        """What the UI and renderers must show (correction always wins)."""
        return self.corrected_text if self.corrected_text is not None else self.text
