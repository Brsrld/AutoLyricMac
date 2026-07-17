"""Claude vision re-ranking: the model LOOKS at candidate photos and picks
the ones that actually fit the lyric's soul (keyword ranking can't see).

Thumbnails only (tiny, free); one request per scene; results cached by
scene+candidate set so a regenerate never pays twice. Fails soft: any
error keeps the keyword order.
"""

import base64
import json
import urllib.request


def _fetch_thumb(url, timeout=20):
    req = urllib.request.Request(
        url, headers={"User-Agent": "AutoLyricMac/0.4 (local app)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(400_000)
    kind = "jpeg"
    if data[:4] == b"\x89PNG":
        kind = "png"
    return base64.standard_b64encode(data).decode(), f"image/{kind}"


def claude_vision_order(candidates, scene, theme, api_key,
                        opener=urllib.request.urlopen, max_images=12):
    """Order candidate indexes best-first by looking at the thumbnails.

    Returns (order, none_fit): `order` is candidate indexes best-first;
    `none_fit` is True when Claude judged that none of the shown photos
    genuinely fit the line (so the caller can draw the scene with AI
    instead of forcing an irrelevant stock photo). `candidates` is a
    RankedMedia list (uses .candidate.thumb_url). Raises on failure — the
    caller falls back to keyword order.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import llm_cache

    subset = [r for r in candidates if r.candidate.thumb_url][:max_images]
    if len(subset) < 2:
        return list(range(len(candidates))), False
    refs = [f"{r.candidate.provider}:{r.candidate.provider_ref}"
            for r in subset]
    ck = llm_cache.key_for("vrank", scene.get("lyric") or "",
                           scene.get("emotion", ""), theme or "", *refs)
    cached = llm_cache.get_json(ck)
    if isinstance(cached, dict):
        order, none_fit = cached.get("order") or [], bool(cached.get("none_fit"))
    elif isinstance(cached, list):          # legacy cache entry
        order, none_fit = cached, False
    else:
        order = none_fit = None
    if order is None:
        content = []
        for i, r in enumerate(subset):
            b64, mime = _fetch_thumb(r.candidate.thumb_url)
            content.append({"type": "text", "text": f"Image {i + 1}:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": mime, "data": b64}})
        content.append({"type": "text", "text": (
            f"Lyric line: \"{scene.get('lyric') or '(instrumental)'}\"\n"
            f"Mood: {scene.get('emotion', 'neutral')}. "
            f"Song theme: {theme or 'unknown'}.\n"
            "Rank the images that genuinely fit this line's meaning/mood for "
            "a cinematic lyric video, best first. Be strict — leave OUT any "
            "image that is off-topic or generic. Reply ONLY as JSON: "
            '{"order":[best-first image numbers that fit], '
            '"none_fit": true only if NONE of them really fit}.')})
        body = json.dumps({"model": "claude-haiku-4-5-20251001",
                           "max_tokens": 150,
                           "messages": [{"role": "user",
                                         "content": content}]}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with opener(req) as resp:
            text = json.loads(resp.read())["content"][0]["text"]
        obj = json.loads(text[text.find("{"):text.rfind("}") + 1])
        order = [n for n in (obj.get("order") or [])
                 if isinstance(n, int) and 1 <= n <= len(subset)]
        none_fit = bool(obj.get("none_fit")) or not order
        llm_cache.put_json(ck, {"order": order, "none_fit": none_fit})

    picked = [n - 1 for n in order
              if isinstance(n, int) and 1 <= n <= len(subset)]
    rest = [i for i in range(len(candidates)) if i not in picked]
    return picked + rest, none_fit
