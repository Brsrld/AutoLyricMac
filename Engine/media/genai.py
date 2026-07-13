"""AI image generation fallback (Phase 4 spec: fallback-only).

Used ONLY when every stock provider fails for a scene. fal.ai FLUX
(schnell) generates a vertical image from the scene's best query + lyric
mood. The key lives in the Keychain (`fal_api_key`); attribution records
the asset as AI-generated. Transport is injectable for offline tests.
"""

import json
import urllib.request

from .providers import MediaCandidate, MediaProviderError

FAL_ENDPOINT = "https://fal.run/fal-ai/flux/schnell"


def build_prompt(scene, style="photo"):
    """Prompt from the scene's queries/lyric/emotion; two art directions."""
    query = (scene.get("queries") or ["cinematic scenery"])[0]
    emotion = scene.get("emotion", "")
    lyric = scene.get("lyric") or ""
    parts = [query]
    if lyric and style != "doodle":   # lyric text makes FLUX draw words
        parts.append(f'inspired by the lyric "{lyric[:80]}"')
    if emotion and emotion != "neutral":
        parts.append(f"{emotion} mood")
    if style == "doodle":
        parts.append("cute hand-drawn marker doodle illustration on warm "
                     "cream paper, thick dark navy ink outlines, simple "
                     "childlike rounded shapes, flat muted warm colors, "
                     "wobbly hand-drawn lines, vertical composition, "
                     "no photorealism, absolutely no text, no letters, no words, "
                     "no typography, no signature, no watermark")
    else:
        parts.append("cinematic photography, vertical composition, natural "
                     "light, no text, no watermark")
    return ", ".join(parts)


def generate_image(scene, api_key, opener=urllib.request.urlopen,
                   style="photo"):
    """Generate one vertical image; returns (MediaCandidate, image_bytes).

    Results are cached by prompt in Cache/genai/ — the same prompt is never
    paid for twice (regenerates, replans and other songs reuse it free).
    """
    prompt = build_prompt(scene, style)
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    import llm_cache
    cache_path = llm_cache.cached_image_path(prompt)
    if cache_path.exists():
        cand = MediaCandidate(
            provider="fal_ai", provider_ref=f"gen-{scene.get('scene_index', 0)}",
            kind="photo", width=1088, height=1920, page_url="https://fal.ai",
            download_url=f"cache://{cache_path.name}",
            creator="AI generated (FLUX schnell, cached)",
            license="AI-generated via fal.ai", query=prompt[:120])
        return cand, cache_path.read_bytes()
    body = json.dumps({
        "prompt": prompt,
        "image_size": {"width": 1088, "height": 1920},
        "num_images": 1,
    }).encode()
    req = urllib.request.Request(FAL_ENDPOINT, data=body, headers={
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"})
    try:
        with opener(req) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:
        raise MediaProviderError(f"AI generation failed: {exc}") from exc
    images = payload.get("images") or []
    url = images[0].get("url") if images else None
    if not url:
        raise MediaProviderError("AI generation returned no image.")
    img_req = urllib.request.Request(url)
    try:
        with opener(img_req) as resp:
            data = resp.read()
    except Exception as exc:
        raise MediaProviderError(f"Could not download the generated "
                                 f"image: {exc}") from exc
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    cand = MediaCandidate(
        provider="fal_ai", provider_ref=f"gen-{scene.get('scene_index', 0)}",
        kind="photo", width=1088, height=1920, page_url="https://fal.ai",
        download_url=url, creator="AI generated (FLUX schnell)",
        license="AI-generated via fal.ai", query=prompt[:120])
    return cand, data
