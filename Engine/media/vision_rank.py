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
                        opener=urllib.request.urlopen, max_images=6):
    """Return candidate indexes ordered best-first by looking at thumbs.

    `candidates`: RankedMedia list (uses .candidate.thumb_url). Raises on
    failure — caller falls back to keyword order.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import llm_cache

    subset = [r for r in candidates if r.candidate.thumb_url][:max_images]
    if len(subset) < 2:
        return list(range(len(candidates)))
    refs = [f"{r.candidate.provider}:{r.candidate.provider_ref}"
            for r in subset]
    ck = llm_cache.key_for("vrank", scene.get("lyric") or "",
                           scene.get("emotion", ""), theme or "", *refs)
    cached = llm_cache.get_json(ck)
    if cached is not None:
        order = cached
    else:
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
            "Which images best carry this line's soul in a cinematic lyric "
            "video? Reply ONLY with a JSON array of image numbers, best "
            "first, e.g. [3,1,2].")})
        body = json.dumps({"model": "claude-haiku-4-5-20251001",
                           "max_tokens": 100,
                           "messages": [{"role": "user",
                                         "content": content}]}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with opener(req) as resp:
            text = json.loads(resp.read())["content"][0]["text"]
        order = json.loads(text[text.find("["):text.rfind("]") + 1])
        llm_cache.put_json(ck, order)

    picked = [n - 1 for n in order
              if isinstance(n, int) and 1 <= n <= len(subset)]
    rest = [i for i in range(len(candidates)) if i not in picked]
    return picked + rest
