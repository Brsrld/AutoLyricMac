"""Automatic Turkish translation (local, no LLM/API).

Every lyric line gets a Turkish translation under the original, whatever the
source language: Argos Translate (offline CTranslate2 models) translates
directly or pivots through English; missing language-pair models are
fetched from the Argos index once and cached locally. User-entered
translations are never overwritten. The translator callable is injectable
so all logic is unit-testable without models.
"""


def claude_translate_lines(lines, api_key, source_lang="auto"):
    """High-quality lyric translation via the Anthropic API (optional).

    Translates all lines in one request preserving poetic register; returns
    a list of Turkish strings (same length) or raises on any failure so the
    caller can fall back to Argos. The key comes from the Keychain and is
    never logged.
    """
    import json as _json
    import urllib.request as _rq

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
    body = _json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content":
                      "Translate these song lyric lines to natural, poetic "
                      "Turkish. Keep the meaning and emotional tone; do not "
                      "explain. Reply with ONLY a JSON array of strings, one "
                      f"per line, same order.\n\n{numbered}"}],
    }).encode()
    req = _rq.Request("https://api.anthropic.com/v1/messages", data=body,
                      headers={"x-api-key": api_key,
                               "anthropic-version": "2023-06-01",
                               "content-type": "application/json"})
    with _rq.urlopen(req, timeout=60) as resp:
        payload = _json.loads(resp.read().decode())
    text = payload["content"][0]["text"].strip()
    start, end = text.find("["), text.rfind("]")
    result = _json.loads(text[start:end + 1])
    if not isinstance(result, list) or len(result) != len(lines):
        raise ValueError("unexpected translation payload shape")
    return [str(t).strip() for t in result]


def _argos_translate(text, from_code, to_code="tr"):
    """Default translator backed by Argos; raises on missing pairs."""
    import argostranslate.translate as art
    return art.translate(text, from_code, to_code)


def ensure_argos_pair(from_code, to_code="tr", log=None):
    """Install Argos package(s) for the pair (direct or via en pivot).

    Returns True when translation for the pair should work. Downloads are
    local one-time model fetches from the official Argos index.
    """
    import argostranslate.package as pkg

    def installed_pairs():
        return {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}

    def install(fc, tc):
        if (fc, tc) in installed_pairs():
            return True
        try:
            pkg.update_package_index()
            for p in pkg.get_available_packages():
                if p.from_code == fc and p.to_code == tc:
                    if log:
                        log(f"Downloading translation model {fc}->{tc}…")
                    pkg.install_from_path(p.download())
                    return True
        except Exception as exc:
            if log:
                log(f"Translation model {fc}->{tc} unavailable: {exc}")
        return False

    if from_code == to_code:
        return False
    if install(from_code, to_code):
        return True
    # pivot: X -> en -> tr
    return install(from_code, "en") and install("en", to_code)


def fill_missing_translations(store, job_id, source_lang,
                              translator=_argos_translate, log=None):
    """Translate every untranslated line to Turkish; keep user edits.

    Returns (translated_count, skipped_count). Lines whose translation the
    user already set are left untouched; failures skip the line (surfaced
    via the log) rather than blocking the pipeline.
    """
    payload = store.get_lyrics(job_id)
    if payload is None:
        return 0, 0
    source_lang = (source_lang or "en").lower()[:2]
    if source_lang == "tr":
        return 0, len(payload["lines"])   # already Turkish; nothing to add

    translated = skipped = 0
    for line in payload["lines"]:
        if line.get("translation"):
            skipped += 1
            continue
        text = line["display_text"].strip()
        if not text:
            skipped += 1
            continue
        try:
            result = (translator(text, source_lang, "tr") or "").strip()
        except Exception as exc:
            if log:
                log(f"line {line['line_index']}: translation failed ({exc})")
            skipped += 1
            continue
        if not result or result.lower() == text.lower():
            skipped += 1
            continue
        store.update_line(job_id, line["line_index"], translation=result)
        translated += 1
    return translated, skipped
