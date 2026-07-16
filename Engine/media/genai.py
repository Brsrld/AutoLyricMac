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

# lyric mood -> color direction (keeps white paper from dominating)
MOOD_PALETTES = {
    "love": "warm rose, coral and soft crimson palette, dusk glow",
    "longing": "amber sunset and violet dusk palette, deep warm shadows",
    "joy": "vivid sunny yellow, fresh green and sky blue palette",
    "melancholy": "deep indigo twilight, rainy blue-grey palette",
    "calm": "soft sage, teal and misty morning palette",
    "energy": "bold red, orange and electric blue palette",
    "nostalgia": "sepia, faded gold and olive palette, old photo warmth",
    "loneliness": "cold navy night, sparse lamplight palette",
    "hope": "dawn pastel pink, peach and light gold palette",
    "neutral": "muted warm earth-tone palette",
}


# Selectable art directions for AI-drawn (Doodle template) scenes. Each
# maps to a FLUX prompt fragment ({palette} is filled from the lyric mood);
# `boil` says whether the renderer's hand-drawn "line boil" wobble suits it
# (only the ink storybook look does — it warps realistic frames unpleasantly).
ART_STYLES = {
    "storybook": {
        "label": "Storybook Doodle",
        "boil": True,
        "prompt": ("detailed hand-drawn ink and gouache illustration, thick "
                   "dark navy outlines, {palette}, fully painted colored "
                   "background filling the whole frame with scenery and "
                   "atmosphere (sky, buildings, nature, interior details), "
                   "textured shading, wobbly hand-drawn lines, storybook art, "
                   "vertical composition, no plain white background, "
                   "no photorealism"),
    },
    "ghibli": {
        "label": "Ghibli Anime",
        "boil": False,
        "prompt": ("lush Studio Ghibli inspired anime painting, hand-painted "
                   "scenery, soft painterly watercolor skies with billowing "
                   "clouds, gentle warm light, {palette}, richly detailed "
                   "nature and background, wholesome nostalgic atmosphere, "
                   "cinematic vertical composition, cel-shaded characters, "
                   "highly detailed, no photorealism"),
    },
    "realistic": {
        "label": "Realistic",
        "boil": False,
        "prompt": ("photorealistic cinematic photograph, {palette}, natural "
                   "volumetric lighting, shallow depth of field, subtle film "
                   "grain, ultra detailed, 35mm, vertical composition"),
    },
    "watercolor": {
        "label": "Watercolor",
        "boil": False,
        "prompt": ("delicate watercolor painting, soft wet-on-wet washes, "
                   "visible paper texture, {palette}, loose expressive "
                   "brushwork, dreamy atmosphere, vertical composition"),
    },
    "anime": {
        "label": "Modern Anime",
        "boil": False,
        "prompt": ("modern anime key visual, clean cel shading, crisp line "
                   "art, vibrant {palette}, detailed background art, dramatic "
                   "lighting, vertical composition, high quality"),
    },
    "oil": {
        "label": "Oil Painting",
        "boil": False,
        "prompt": ("rich oil painting, visible impasto brush strokes, "
                   "classical chiaroscuro lighting, {palette}, textured "
                   "canvas, painterly, vertical composition"),
    },
    "caricature": {
        "label": "Caricature",
        "boil": True,
        "prompt": ("a single exaggerated caricature character, thick "
                   "confident hand-inked outlines, oversized expressive "
                   "features, playful humorous cartoon style, flat cel "
                   "shading, {palette}, simple uncluttered background, "
                   "wordless illustration, vertical composition, "
                   "no photorealism"),
    },
    # legacy fallback used when stock search fails on a photo template
    "photo": {
        "label": "Photo",
        "boil": False,
        "prompt": ("cinematic photography, vertical composition, natural "
                   "light"),
    },
}

_NO_TEXT = ("absolutely no text, no letters, no words, no typography, "
            "no captions, no title, no speech bubbles, no comic lettering, "
            "no signature, no watermark")


def _resolve_style(style):
    """Normalize an art-style key: 'doodle' alias, unknown -> 'photo'."""
    if style == "doodle":            # backward-compatible alias
        return "storybook"
    return style if style in ART_STYLES else "photo"


def art_style_uses_boil(style):
    """Whether the renderer's line-boil wobble suits this art style."""
    return bool(ART_STYLES[_resolve_style(style)].get("boil"))


def build_prompt(scene, style="photo"):
    """Prompt from the scene's queries/emotion and the chosen art style."""
    style = _resolve_style(style)
    spec = ART_STYLES[style]
    query = (scene.get("queries") or ["cinematic scenery"])[0]
    emotion = scene.get("emotion", "")
    lyric = scene.get("lyric") or ""
    parts = [query]
    # only the pure photo fallback quotes the lyric; drawn styles never do,
    # so FLUX is not tempted to render (garbled) song text into the art
    if lyric and style == "photo":
        parts.append(f'inspired by the lyric "{lyric[:80]}"')
    if emotion and emotion != "neutral":
        parts.append(f"{emotion} mood")
    palette = MOOD_PALETTES.get(emotion, MOOD_PALETTES["neutral"])
    parts.append(spec["prompt"].format(palette=palette))
    parts.append(_NO_TEXT)
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
