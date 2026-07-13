"""Deterministic lyric semantics (Phase 4).

Maps a lyric line to subjects, emotion scores, and stock-search queries using
a curated English + Turkish lexicon — the app must work without any LLM.
`extract_semantics` is the default implementation of the semantics interface;
an optional LLM provider can replace it later behind the same signature:
callable(text) -> {"subjects", "emotions", "queries", "matched"}.

Matching is prefix-based (token starts with the lexicon stem) so English
plurals and Turkish agglutinative suffixes both hit: "windows" -> "window",
"yollarda" -> "yol".
"""

import re
import unicodedata

EMOTIONS = ("love", "longing", "joy", "melancholy", "calm", "energy",
            "nostalgia", "loneliness", "hope")

# stem -> (subjects, {emotion: weight}, query templates)
_LEX = {
    # --- English: light & time of day ---
    "light":    (["light"], {"hope": 1}, ["warm window light", "soft light rays"]),
    "sun":      (["sun", "sky"], {"joy": 1, "hope": 1}, ["golden sunlight", "sun through trees"]),
    "moon":     (["moon", "night sky"], {"calm": 1, "longing": 1}, ["moonlight night sky", "full moon clouds"]),
    "star":     (["stars", "night sky"], {"hope": 1, "calm": 1}, ["starry night sky", "stars long exposure"]),
    "night":    (["night"], {"melancholy": 1, "calm": 1}, ["city night lights bokeh", "quiet night street"]),
    "morning":  (["morning"], {"hope": 1, "calm": 1}, ["misty morning light", "morning coffee window"]),
    "shadow":   (["shadow"], {"melancholy": 1}, ["long shadows evening", "silhouette against light"]),
    "dark":     (["darkness"], {"melancholy": 1, "loneliness": 1}, ["dark moody clouds", "dim room curtains"]),
    # --- weather & nature ---
    "rain":     (["rain"], {"melancholy": 1, "calm": 1}, ["rain on window glass", "person walking rain umbrella"]),
    "storm":    (["storm", "sky"], {"energy": 1, "melancholy": 1}, ["storm clouds timelapse", "lightning dark sky"]),
    "snow":     (["snow", "winter"], {"calm": 1, "nostalgia": 1}, ["snow falling street lamp", "winter snowy field"]),
    "wind":     (["wind"], {"longing": 1}, ["wind blowing grass field", "hair in the wind"]),
    "sea":      (["sea", "water"], {"calm": 1, "longing": 1}, ["calm sea horizon", "waves on shore slow"]),
    "ocean":    (["ocean", "water"], {"calm": 1, "longing": 1}, ["ocean waves aerial", "deep blue ocean"]),
    "river":    (["river", "water"], {"calm": 1}, ["river flowing forest", "river stones close"]),
    "water":    (["water"], {"calm": 1}, ["water surface ripples", "light reflecting water"]),
    "fire":     (["fire"], {"energy": 1, "love": 1}, ["campfire flames night", "candle flame dark"]),
    "mountain": (["mountain"], {"calm": 1, "hope": 1}, ["misty mountain range", "mountain sunrise"]),
    "forest":   (["forest", "trees"], {"calm": 1}, ["sunlight through forest", "foggy forest path"]),
    "flower":   (["flowers"], {"joy": 1, "love": 1}, ["wildflowers field", "flower close up soft"]),
    "sky":      (["sky"], {"hope": 1, "calm": 1}, ["dramatic clouds sky", "pastel sunset sky"]),
    "winter":   (["winter"], {"nostalgia": 1, "melancholy": 1}, ["bare trees winter fog", "frozen window frost"]),
    "summer":   (["summer"], {"joy": 1, "nostalgia": 1}, ["summer meadow golden hour", "kids running summer field"]),
    "autumn":   (["autumn"], {"nostalgia": 1, "melancholy": 1}, ["falling autumn leaves", "autumn park bench"]),
    "spring":   (["spring"], {"hope": 1, "joy": 1}, ["blossoming tree spring", "fresh green leaves"]),
    # --- places ---
    "home":     (["home"], {"nostalgia": 1, "calm": 1}, ["cozy home interior warm", "old family house exterior"]),
    "house":    (["house", "home"], {"nostalgia": 1}, ["old house facade", "warm lit house evening"]),
    "window":   (["window"], {"longing": 1, "calm": 1}, ["person by window light", "rain on window curtains"]),
    "door":     (["door"], {"longing": 1}, ["old wooden door", "open door light hallway"]),
    "kitchen":  (["kitchen", "home"], {"nostalgia": 1, "calm": 1}, ["vintage kitchen morning", "cooking hands kitchen"]),
    "road":     (["road", "journey"], {"longing": 1}, ["empty road horizon", "country road aerial"]),
    "street":   (["street", "city"], {"melancholy": 1, "nostalgia": 1}, ["old town street evening", "wet street reflections"]),
    "city":     (["city"], {"energy": 1, "loneliness": 1}, ["city skyline dusk", "crowd crossing street"]),
    "train":    (["train", "journey"], {"nostalgia": 1, "longing": 1}, ["old train railway", "view from train window"]),
    "station":  (["station", "journey"], {"longing": 1, "melancholy": 1}, ["empty train station", "railway platform fog"]),
    "bridge":   (["bridge"], {"longing": 1}, ["old stone bridge mist", "bridge over river dusk"]),
    "garden":   (["garden"], {"calm": 1, "nostalgia": 1}, ["overgrown garden sunlight", "grandmother garden flowers"]),
    "school":   (["school", "childhood"], {"nostalgia": 1}, ["empty school corridor", "vintage classroom desks"]),
    # --- people & relations ---
    "mother":   (["mother", "family"], {"love": 1, "nostalgia": 1}, ["mother and child embrace", "mother cooking kitchen"]),
    "father":   (["father", "family"], {"love": 1, "nostalgia": 1}, ["father and child walking", "father hands working"]),
    "child":    (["child", "childhood"], {"joy": 1, "nostalgia": 1}, ["children playing street", "child running field"]),
    "friend":   (["friends"], {"joy": 1}, ["friends laughing together", "friends walking sunset"]),
    "hand":     (["hands"], {"love": 1}, ["holding hands close", "old hands together"]),
    "eye":      (["eyes", "face"], {"love": 1, "longing": 1}, ["closed eyes portrait soft", "looking away portrait"]),
    "heart":    (["heart"], {"love": 1}, ["heart shape hands", "couple embrace silhouette"]),
    "kiss":     (["couple"], {"love": 1, "joy": 1}, ["couple kissing silhouette", "forehead kiss close"]),
    "dance":    (["dancing"], {"joy": 1, "energy": 1}, ["couple dancing kitchen", "dancing silhouette lights"]),
    "smile":    (["smile", "face"], {"joy": 1}, ["genuine smile portrait", "laughing candid moment"]),
    "tear":     (["tears", "face"], {"melancholy": 1}, ["tear on cheek close", "sad eyes window light"]),
    "cry":      (["tears"], {"melancholy": 1}, ["person crying window", "rain and tears mood"]),
    # --- states & abstractions ---
    "love":     (["love"], {"love": 2}, ["couple embrace golden hour", "love letters vintage"]),
    "alone":    (["solitude"], {"loneliness": 2}, ["person alone bench", "single figure empty street"]),
    "lonely":   (["solitude"], {"loneliness": 2}, ["lonely figure fog", "empty chair by window"]),
    "goodbye":  (["farewell"], {"melancholy": 1, "longing": 1}, ["waving goodbye station", "leaving suitcase door"]),
    "memory":   (["memory"], {"nostalgia": 2}, ["old photo album hands", "faded photographs box"]),
    "remember": (["memory"], {"nostalgia": 2}, ["looking at old photos", "vintage film photos table"]),
    "dream":    (["dream"], {"hope": 1, "calm": 1}, ["dreamy clouds soft focus", "sleeping peaceful morning"]),
    "young":    (["youth", "childhood"], {"nostalgia": 1, "joy": 1}, ["young friends vintage summer", "youth running sunset"]),
    "old":      (["age", "memory"], {"nostalgia": 1}, ["old man portrait window", "antique objects table"]),
    "time":     (["time"], {"nostalgia": 1}, ["old clock closeup", "hourglass sand light"]),
    "wait":     (["waiting"], {"longing": 1}, ["person waiting window", "waiting at station alone"]),
    "miss":     (["longing"], {"longing": 2}, ["looking at horizon alone", "empty side of bed"]),
    "hold":     (["embrace"], {"love": 1}, ["tight embrace couple", "holding each other close"]),
    "distance": (["distance", "journey"], {"longing": 1, "loneliness": 1}, ["far horizon road", "looking into distance"]),
    "far":      (["distance"], {"longing": 1}, ["distant hills haze", "far away lights night"]),
    "return":   (["reunion", "journey"], {"hope": 1, "longing": 1}, ["airport reunion hug", "coming home door"]),
    "walk":     (["walking"], {"calm": 1}, ["walking away path", "feet walking cobblestone"]),
    "run":      (["running"], {"energy": 1}, ["running through field", "running city night"]),
    "sing":     (["music"], {"joy": 1}, ["vinyl record player", "singing into hairbrush fun"]),
    "song":     (["music"], {"nostalgia": 1}, ["old radio close", "cassette tapes retro"]),
    "bright":   (["light"], {"joy": 1, "hope": 1}, ["bright bokeh lights", "sunbeam through window"]),
    "cold":     (["cold"], {"loneliness": 1, "melancholy": 1}, ["breath in cold air", "frost on glass"]),
    "warm":     (["warmth", "home"], {"love": 1, "calm": 1}, ["warm blanket coffee", "warm lamp light room"]),
    "golden":   (["light"], {"nostalgia": 1, "joy": 1}, ["golden hour field", "golden light portrait"]),
    "word":     (["letters"], {"longing": 1}, ["handwritten letter close", "typewriter keys vintage"]),
    "letter":   (["letters", "memory"], {"longing": 1, "nostalgia": 1}, ["old letters ribbon", "writing letter by hand"]),
    # --- Turkish ---
    "aşk":      (["love"], {"love": 2}, ["couple embrace golden hour", "love silhouette sunset"]),
    "sevda":    (["love"], {"love": 2, "longing": 1}, ["longing lovers apart", "old love letters"]),
    "sevgili":  (["love"], {"love": 2}, ["couple holding hands", "lovers walking street"]),
    "kalp":     (["heart"], {"love": 1}, ["heart shape hands", "couple embrace silhouette"]),
    "gece":     (["night"], {"melancholy": 1, "calm": 1}, ["city night lights bokeh", "quiet night street"]),
    "gündüz":   (["day"], {"calm": 1}, ["daylight street scene", "bright afternoon park"]),
    "güneş":    (["sun", "sky"], {"joy": 1, "hope": 1}, ["golden sunlight", "sun through trees"]),
    "ay":       (["moon", "night sky"], {"calm": 1, "longing": 1}, ["moonlight night sky", "full moon clouds"]),
    "yıldız":   (["stars", "night sky"], {"hope": 1}, ["starry night sky", "stars long exposure"]),
    "gökyüzü":  (["sky"], {"hope": 1, "calm": 1}, ["dramatic clouds sky", "pastel sunset sky"]),
    "deniz":    (["sea", "water"], {"calm": 1, "longing": 1}, ["calm sea horizon", "waves on shore slow"]),
    "yağmur":   (["rain"], {"melancholy": 1, "calm": 1}, ["rain on window glass", "walking in rain umbrella"]),
    "kar":      (["snow", "winter"], {"calm": 1, "nostalgia": 1}, ["snow falling street lamp", "winter snowy field"]),
    "rüzgar":   (["wind"], {"longing": 1}, ["wind blowing grass field", "hair in the wind"]),
    "ateş":     (["fire"], {"energy": 1, "love": 1}, ["campfire flames night", "candle flame dark"]),
    "yol":      (["road", "journey"], {"longing": 1}, ["empty road horizon", "country road aerial"]),
    "sokak":    (["street", "city"], {"nostalgia": 1}, ["old town street evening", "wet street reflections"]),
    "şehir":    (["city"], {"energy": 1, "loneliness": 1}, ["city skyline dusk", "crowd crossing street"]),
    "tren":     (["train", "journey"], {"nostalgia": 1, "longing": 1}, ["old train railway", "view from train window"]),
    "ev":       (["home"], {"nostalgia": 1, "calm": 1}, ["cozy home interior warm", "old family house exterior"]),
    "pencere":  (["window"], {"longing": 1, "calm": 1}, ["person by window light", "rain on window curtains"]),
    "kapı":     (["door"], {"longing": 1}, ["old wooden door", "open door light hallway"]),
    "anne":     (["mother", "family"], {"love": 1, "nostalgia": 1}, ["mother and child embrace", "mother cooking kitchen"]),
    "baba":     (["father", "family"], {"love": 1, "nostalgia": 1}, ["father and child walking", "father hands working"]),
    "çocuk":    (["child", "childhood"], {"joy": 1, "nostalgia": 1}, ["children playing street", "child running field"]),
    "göz":      (["eyes", "face"], {"love": 1, "longing": 1}, ["closed eyes portrait soft", "looking away portrait"]),
    "el":       (["hands"], {"love": 1}, ["holding hands close", "old hands together"]),
    "gül":      (["flowers", "smile"], {"love": 1, "joy": 1}, ["red rose close up", "genuine smile portrait"]),
    "ağla":     (["tears"], {"melancholy": 2}, ["person crying window", "tear on cheek close"]),
    "gözyaş":   (["tears"], {"melancholy": 2}, ["tear on cheek close", "sad eyes window light"]),
    "yalnız":   (["solitude"], {"loneliness": 2}, ["person alone bench", "single figure empty street"]),
    "hasret":   (["longing"], {"longing": 2}, ["looking at horizon alone", "waiting by phone vintage"]),
    "özle":     (["longing"], {"longing": 2}, ["looking at old photos", "empty side of bed"]),
    "veda":     (["farewell"], {"melancholy": 1, "longing": 1}, ["waving goodbye station", "leaving suitcase door"]),
    "hatıra":   (["memory"], {"nostalgia": 2}, ["old photo album hands", "faded photographs box"]),
    "anı":      (["memory"], {"nostalgia": 2}, ["old photo album hands", "vintage film photos table"]),
    "rüya":     (["dream"], {"hope": 1, "calm": 1}, ["dreamy clouds soft focus", "sleeping peaceful morning"]),
    "zaman":    (["time"], {"nostalgia": 1}, ["old clock closeup", "hourglass sand light"]),
    "bekle":    (["waiting"], {"longing": 1}, ["person waiting window", "waiting at station alone"]),
    "uzak":     (["distance"], {"longing": 1, "loneliness": 1}, ["far horizon road", "looking into distance"]),
    "dön":      (["reunion", "journey"], {"hope": 1, "longing": 1}, ["coming home door", "airport reunion hug"]),
    "sarıl":    (["embrace"], {"love": 1}, ["tight embrace couple", "holding each other close"]),
    "dans":     (["dancing"], {"joy": 1, "energy": 1}, ["couple dancing kitchen", "dancing silhouette lights"]),
    "şarkı":    (["music"], {"nostalgia": 1}, ["old radio close", "vinyl record player"]),
    "mektup":   (["letters", "memory"], {"longing": 1, "nostalgia": 1}, ["old letters ribbon", "handwritten letter close"]),
    "sıcak":    (["warmth", "home"], {"love": 1, "calm": 1}, ["warm blanket coffee", "warm lamp light room"]),
    "soğuk":    (["cold"], {"loneliness": 1, "melancholy": 1}, ["breath in cold air", "frost on glass"]),
    "ışık":     (["light"], {"hope": 1}, ["warm window light", "soft light rays"]),
    "karanlık": (["darkness"], {"melancholy": 1, "loneliness": 1}, ["dark moody clouds", "dim room curtains"]),
    "bahar":    (["spring"], {"hope": 1, "joy": 1}, ["blossoming tree spring", "fresh green leaves"]),
    "kış":      (["winter"], {"nostalgia": 1, "melancholy": 1}, ["bare trees winter fog", "frozen window frost"]),
    "yaz":      (["summer"], {"joy": 1, "nostalgia": 1}, ["summer meadow golden hour", "kids running summer field"]),
    "toprak":   (["earth"], {"nostalgia": 1}, ["hands in soil", "dry earth field"]),
    "taş":      (["stone"], {"melancholy": 1}, ["stone wall texture", "pebbles on shore"]),
    "su":       (["water"], {"calm": 1}, ["water surface ripples", "light reflecting water"]),
}

_GENERIC_QUERIES = ["soft abstract light texture", "warm bokeh background",
                    "gentle clouds sky minimal"]

# dominant emotion -> mood-carrying stock queries (song-level fallback)
EMOTION_QUERIES = {
    "love": ["romantic couple golden hour", "soft intimate moment film"],
    "longing": ["person gazing at horizon", "empty road wistful mood"],
    "joy": ["friends laughing sunlight", "joyful dancing warm light"],
    "melancholy": ["moody rainy window portrait", "lonely walk foggy street"],
    "calm": ["peaceful nature morning mist", "quiet lake reflection dawn"],
    "energy": ["city lights motion night", "concert crowd energy lights"],
    "nostalgia": ["vintage film photo memories", "old family album retro"],
    "loneliness": ["solitary figure empty field", "single window lit at night"],
    "hope": ["sunrise over hills warm", "light rays through clouds"],
    "neutral": ["cinematic atmospheric landscape", "warm analog film mood"],
}


def _norm(text):
    t = unicodedata.normalize("NFC", (text or "").lower())
    return re.sub(r"[^\w\sğüşıöçâîû']", " ", t)


def _match(token):
    """Longest lexicon stem the token starts with (min stem length 2)."""
    best = None
    for stem in _LEX:
        if token.startswith(stem) and (best is None or len(stem) > len(best)):
            # keep short stems honest: token may extend a stem by suffixes only
            if len(stem) >= 3 or token == stem:
                best = stem
    return best


def extract_semantics(text):
    """Deterministic subjects/emotions/queries for one lyric line."""
    subjects, queries, matched = [], [], []
    emotions = {e: 0.0 for e in EMOTIONS}
    for token in _norm(text).split():
        stem = _match(token)
        if stem is None or stem in matched:
            continue
        matched.append(stem)
        subj, emo, tmpl = _LEX[stem]
        for s in subj:
            if s not in subjects:
                subjects.append(s)
        for name, w in emo.items():
            emotions[name] += w
        for q in tmpl:
            if q not in queries:
                queries.append(q)

    total = sum(emotions.values())
    if total > 0:
        emotions = {k: round(v / total, 3) for k, v in emotions.items()}
    if not queries:
        queries = list(_GENERIC_QUERIES)
    return {
        "subjects": subjects[:6],
        "emotions": emotions,
        "queries": queries[:5],
        "matched": matched,
    }


def claude_semantics(line_texts, title_hint, api_key):
    """Optional LLM semantics: per-line emotion/subjects/stock queries.

    One batched request; returns {line_text: semantics_dict} shaped exactly
    like extract_semantics output. Raises on any failure so the caller
    falls back to the lexicon.
    """
    import json
    import urllib.request

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(line_texts))
    prompt = (
        f"Song: {title_hint or 'unknown'}\nLyric lines:\n{numbered}\n\n"
        "For EACH line, give visual direction for a licensed stock-photo "
        "search that captures the line's meaning and the song's mood. "
        "Reply ONLY with a JSON array; element i for line i+1: "
        '{"emotion": one of ' + str(list(EMOTIONS)) + ', '
        '"subjects": [1-3 short nouns], '
        '"queries": [3 concrete English stock-photo search phrases, '
        "cinematic, no text/logos]}")
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode())
    text = payload["content"][0]["text"]
    items = json.loads(text[text.find("["):text.rfind("]") + 1])
    if len(items) != len(line_texts):
        raise ValueError("semantic payload length mismatch")
    out = {}
    for line, item in zip(line_texts, items):
        emotions = {e: 0.0 for e in EMOTIONS}
        if item.get("emotion") in emotions:
            emotions[item["emotion"]] = 1.0
        out[line] = {"subjects": [str(s) for s in item.get("subjects", [])][:4],
                     "emotions": emotions,
                     "queries": [str(q) for q in item.get("queries", [])][:4],
                     "matched": ["llm"]}
    return out


def dominant_emotion(emotions):
    """Highest-scoring emotion name, or 'neutral' when nothing scored."""
    if not emotions or all(v == 0 for v in emotions.values()):
        return "neutral"
    return max(emotions.items(), key=lambda kv: kv[1])[0]
