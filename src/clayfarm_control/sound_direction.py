"""Sound Direction Card contract and a deterministic, model-agnostic compiler.

An artist writes a short free-form note in whatever language they think in.  That
note is *source text*: it is kept for review and traceability, but it is never
handed to a generator as a prompt.  Instead the caller fills a bounded **Sound
Direction Card** (enumerations and bounded numbers only), and this module
compiles that card into a deterministic English prompt plus explicit ``must_not``
constraints.

Design rules:

* Only the Python standard library is used.
* Every failure is a :class:`~clayfarm_control.common.CFError` with a stable code.
* The card accepts no model settings (no sampler, steps, guidance, checkpoint...).
  Model behaviour stays profile-locked.
* Compilation is pure and deterministic: the same card, duration, seed and
  variation index always produce byte-identical canonical output.
* Nothing here claims that a neural model exists, is cached, or is approved.
"""
from __future__ import annotations

import math

from .common import CFError, canonical, sha

CARD_SCHEMA_VERSION = 1
COMPILED_SCHEMA_VERSION = 1
COMPILER_VERSION = "sound-direction-compiler/1"

#: Controlled vocabularies.  Unknown tokens are rejected instead of silently
#: forwarded, so the compiled prompt can never contain caller-authored prose.
CATEGORIES = (
    "ambience", "creature", "destruction", "foley", "impact", "magic",
    "mechanical", "movement", "nature", "pickup", "ui", "weapon",
)
ACTIONS = (
    "bounce", "break", "burn", "charge", "click", "crush", "explode", "hit",
    "pour", "rattle", "release", "scrape", "slide", "splash", "step", "swing",
    "tear", "whoosh",
)
MATERIALS = (
    "ceramic", "cloth", "earth", "flesh", "glass", "ice", "leaves", "metal",
    "paper", "plastic", "rope", "sand", "stone", "water", "wood",
)
TEXTURES = (
    "airy", "clean", "crackle", "gritty", "hiss", "metallic_ring", "noisy",
    "rumble", "thud", "tonal",
)
MUST_TOKENS = (
    "air_cut", "clean_finish", "descending_sweep", "dry_capture",
    "no_impact", "one_transient", "short_whoosh",
)
SWEEPS = ("none", "high_to_mid", "mid_to_high", "rising", "falling")
SIZES = ("tiny", "small", "medium", "large", "huge")
ENERGIES = ("gentle", "moderate", "strong", "violent")
ATTACKS = ("instant", "fast", "medium", "slow")
TAILS = ("none", "short", "medium", "long")
SPACES = ("dry", "small_room", "large_room", "hall", "outdoor", "cave", "underwater")
PITCHES = ("low", "mid", "high")
MOODS = ("neutral", "playful", "tense", "heroic", "eerie", "comedic", "warm", "harsh")
MUST_NOT_TOKENS = (
    "airflow", "background_noise", "blowing", "breath", "clipping", "distortion",
    "fade_in", "looping_artifacts", "melody", "metal_impact", "music", "reverb_tail",
    "speech", "steam", "stereo_width", "sustained_drone", "sustained_wind", "tonal_drone",
    "vocals",
)

#: Constraints every SFX card inherits.  They keep a sound-effect request from
#: drifting into music or narration.
_BASELINE_MUST_NOT = ("clipping", "music", "speech", "vocals")

_LIST_FIELDS = {
    "materials": (MATERIALS, 3),
    "textures": (TEXTURES, 4),
    "must": (MUST_TOKENS, 8),
    "must_not": (MUST_NOT_TOKENS, 8),
    "reference_tags": (None, 6),
}
_ENUM_FIELDS = {
    "size": (SIZES, "medium"),
    "energy": (ENERGIES, "moderate"),
    "attack": (ATTACKS, "fast"),
    "tail": (TAILS, "short"),
    "space": (SPACES, "dry"),
    "pitch": (PITCHES, "mid"),
    "mood": (MOODS, "neutral"),
    "sweep": (SWEEPS, "none"),
}
CARD_FIELDS = frozenset(
    {"schema_version", "category", "action", "brightness", "noise_ratio", "frequency_hz", "layer_count", "loopable"}
    | set(_ENUM_FIELDS)
    | set(_LIST_FIELDS)
)

_TAG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
_BRIGHTNESS_LABELS = ((0.2, "very dark"), (0.4, "dark"), (0.6, "neutral"), (0.8, "bright"))
MAX_SOURCE_TEXT = 2000

# The draft helper is deliberately a suggestion engine, not a generative
# prompt rewriter. It recognizes a small bilingual vocabulary and always
# returns ``needs_review`` so an artist confirms or edits the card.
_DRAFT_CATEGORY_HINTS = (
    (("검", "칼", "blade", "sword"), "weapon"),
    (("타격", "충돌", "impact", "hit"), "impact"),
    (("버튼", "ui", "클릭", "click"), "ui"),
    (("발걸음", "걷", "step", "foot"), "movement"),
    (("바람", "비", "물", "nature", "wind"), "nature"),
)
_DRAFT_ACTION_HINTS = (
    (("휙", "휘두", "가르", "swish", "whoosh"), "whoosh"),
    (("타격", "부딪", "충돌", "impact", "hit"), "hit"),
    (("폭발", "explode"), "explode"),
    (("발걸음", "걷", "step"), "step"),
    (("클릭", "click"), "click"),
)
_DRAFT_TEXTURE_HINTS = (
    (("공기", "바람", "airy", "wind"), "airy"),
    (("날카", "쉭", "hiss", "sharp"), "hiss"),
    (("금속", "metal"), "metallic_ring"),
)
_DRAFT_NEGATIVE_HINTS = (
    (("입김", "숨", "breath"), "breath"),
    (("뿜", "blowing"), "blowing"),
    (("지속적인 바람", "계속 부는", "sustained wind"), "sustained_wind"),
    (("금속 충돌 없이", "금속 충돌 제외", "metal impact without", "no metal impact"), "metal_impact"),
    (("잔향 없이", "무잔향", "without reverb"), "reverb_tail"),
)


def _enum(value, allowed, name):
    if not isinstance(value, str) or value not in allowed:
        raise CFError("invalid_direction", f"{name} must be one of: {', '.join(allowed)}")
    return value


def _tag(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 32:
        raise CFError("invalid_direction", "reference_tags entries must be 1..32 characters")
    if value[0] not in _TAG_CHARS or value[0] in "_-" or set(value) - _TAG_CHARS:
        raise CFError("invalid_direction", "reference_tags entries must be lowercase a-z0-9_- slugs")
    return value


def _token_list(direction, name):
    allowed, limit = _LIST_FIELDS[name]
    raw = direction.get(name, [])
    if not isinstance(raw, list) or isinstance(raw, bool):
        raise CFError("invalid_direction", f"{name} must be a list")
    if len(raw) > limit:
        raise CFError("invalid_direction", f"{name} accepts at most {limit} entries")
    items = [_tag(item) if allowed is None else _enum(item, allowed, name) for item in raw]
    # Sorted + de-duplicated so that caller ordering cannot change the card hash.
    return sorted(set(items))


def validate_direction(direction) -> dict:
    """Validate a Sound Direction Card and return its normalized form.

    The returned card has a fixed key set and canonical ordering, so
    :func:`card_hash` is stable across callers and processes.
    """
    if not isinstance(direction, dict):
        raise CFError("invalid_direction", "direction must be an object")
    unknown = sorted(set(direction) - CARD_FIELDS)
    if unknown:
        raise CFError("invalid_direction", f"Unknown direction field: {unknown[0]}")
    version = direction.get("schema_version", CARD_SCHEMA_VERSION)
    if version != CARD_SCHEMA_VERSION or isinstance(version, bool):
        raise CFError("invalid_direction", f"direction.schema_version must be {CARD_SCHEMA_VERSION}")

    card = {
        "schema_version": CARD_SCHEMA_VERSION,
        "category": _enum(direction.get("category"), CATEGORIES, "category"),
        "action": _enum(direction.get("action"), ACTIONS, "action"),
    }
    for name, (allowed, default) in _ENUM_FIELDS.items():
        card[name] = _enum(direction.get(name, default), allowed, name)
    for name in _LIST_FIELDS:
        card[name] = _token_list(direction, name)

    brightness = direction.get("brightness", 0.5)
    if isinstance(brightness, bool) or not isinstance(brightness, (int, float)):
        raise CFError("invalid_direction", "brightness must be a number in 0..1")
    if not math.isfinite(brightness) or not 0.0 <= brightness <= 1.0:
        raise CFError("invalid_direction", "brightness must be a number in 0..1")
    card["brightness"] = round(float(brightness), 3)

    noise_ratio = direction.get("noise_ratio", 0.5)
    if isinstance(noise_ratio, bool) or not isinstance(noise_ratio, (int, float)):
        raise CFError("invalid_direction", "noise_ratio must be a number in 0..1")
    if not math.isfinite(noise_ratio) or not 0.0 <= noise_ratio <= 1.0:
        raise CFError("invalid_direction", "noise_ratio must be a number in 0..1")
    card["noise_ratio"] = round(float(noise_ratio), 3)

    frequency = direction.get("frequency_hz")
    if frequency is None:
        card["frequency_hz"] = None
    else:
        if not isinstance(frequency, list) or len(frequency) != 2:
            raise CFError("invalid_direction", "frequency_hz must contain exactly two values")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 20 <= value <= 20000 for value in frequency):
            raise CFError("invalid_direction", "frequency_hz values must be numbers in 20..20000")
        if frequency[0] == frequency[1]:
            raise CFError("invalid_direction", "frequency_hz values must differ")
        card["frequency_hz"] = [round(float(value), 1) for value in frequency]

    layers = direction.get("layer_count", 1)
    if isinstance(layers, bool) or not isinstance(layers, int) or not 1 <= layers <= 4:
        raise CFError("invalid_direction", "layer_count must be an integer in 1..4")
    card["layer_count"] = layers

    loopable = direction.get("loopable", False)
    if not isinstance(loopable, bool):
        raise CFError("invalid_direction", "loopable must be boolean")
    card["loopable"] = loopable
    return card


def _contains(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _first_hint(text: str, table, default: str | None = None):
    for hints, token in table:
        if _contains(text, hints):
            return token
    return default


def draft_direction(source_text: str, *, category: str | None = None, action: str | None = None) -> dict:
    """Create a reviewable card suggestion from a short artist note.

    This function intentionally does not attempt open-ended translation. It
    only maps recognized terms to controlled tokens, reports what it could not
    infer, and marks the result ``needs_review``. The returned card must still
    pass through :func:`validate_direction` before compilation.
    """
    source_text = validate_source_text(source_text)
    text = source_text.casefold()
    inferred_category = category or _first_hint(text, _DRAFT_CATEGORY_HINTS)
    inferred_action = action or _first_hint(text, _DRAFT_ACTION_HINTS)
    unresolved = []
    if inferred_category is None:
        inferred_category = "movement"
        unresolved.append("category")
    if inferred_action is None:
        inferred_action = "whoosh"
        unresolved.append("action")

    card = {
        "category": inferred_category,
        "action": inferred_action,
        "materials": ["metal"] if _contains(text, ("금속", "metal")) and inferred_action != "whoosh" else [],
        "textures": sorted({token for hints, token in _DRAFT_TEXTURE_HINTS if _contains(text, hints)}),
        "must": [],
        "must_not": sorted({token for hints, token in _DRAFT_NEGATIVE_HINTS if _contains(text, hints)}),
        "attack": "instant" if _contains(text, ("즉시", "순간", "instant", "sharp", "날카")) else "fast",
        "tail": "short" if _contains(text, ("짧", "short", "휙", "swish", "whoosh")) else "medium",
        "space": "dry" if _contains(text, ("가까", "근접", "dry", "잔향 없이", "무잔향")) else "dry",
        "pitch": "high" if _contains(text, ("높", "고역", "bright", "날카")) else "mid",
        "mood": "harsh" if _contains(text, ("날카", "공격", "harsh")) else "neutral",
        "brightness": 0.85 if _contains(text, ("밝", "고역", "bright", "날카")) else 0.5,
        "noise_ratio": 0.95 if _contains(text, ("공기", "바람", "airy", "noise", "휙")) else 0.5,
        "sweep": "high_to_mid" if _contains(text, ("내려", "고역에서", "descending", "가르")) else "none",
        "frequency_hz": [10000, 3000] if _contains(text, ("공기", "바람", "휙", "가르")) else None,
        "layer_count": 1,
        "loopable": False,
        "reference_tags": [],
    }
    if _contains(text, ("휙", "휘두", "가르", "swish", "whoosh")):
        card["must"] = ["air_cut", "clean_finish", "one_transient", "short_whoosh"]
    if _contains(text, ("한 번", "한번", "single", "one pass")) and "one_transient" not in card["must"]:
        card["must"].append("one_transient")
    card = validate_direction(card)
    return {
        "status": "needs_review",
        "direction": card,
        "unresolved": unresolved,
        "source_text_hash": source_text_hash(source_text),
        "matched": {
            "category": inferred_category,
            "action": inferred_action,
            "positive_tokens": card["must"],
            "negative_tokens": card["must_not"],
        },
    }


def card_hash(card: dict) -> str:
    """Content hash of a normalized card (canonical JSON, sorted keys)."""
    return sha(canonical(card))


def source_text_hash(text: str) -> str:
    """SHA-256 of the artist note.  The note itself never reaches a model."""
    return sha(text.encode("utf-8"))


def validate_source_text(text, name: str = "source_text") -> str:
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_SOURCE_TEXT:
        raise CFError("invalid_spec", f"Provide {name} with 1..{MAX_SOURCE_TEXT} characters")
    return text


def validate_source_text_hash(value, text=None) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise CFError("invalid_spec", "source_text_hash must be a lowercase sha256 hex digest")
    if text is not None and value != source_text_hash(text):
        raise CFError("invalid_spec", "source_text_hash does not match source_text")
    return value


def _label(token: str) -> str:
    return token.replace("_", " ")


def _brightness_label(value: float) -> str:
    for edge, label in _BRIGHTNESS_LABELS:
        if value < edge:
            return label
    return "very bright"


def compile_must_not(card: dict) -> list[str]:
    """Deterministic negative constraints: baseline plus card-implied rules."""
    tokens = set(_BASELINE_MUST_NOT) | set(card["must_not"])
    if card["space"] == "dry":
        tokens.add("reverb_tail")
    if card["tail"] in ("none", "short") and not card["loopable"]:
        tokens.add("sustained_drone")
    if card["action"] == "whoosh":
        # A one-shot whoosh is a transient air cut. Explicitly exclude the
        # continuous airflow interpretations that caused earlier candidates to
        # sound like breath or blowing wind.
        tokens.update(("airflow", "blowing", "breath", "sustained_wind"))
    if card["loopable"]:
        tokens.add("fade_in")
        tokens.add("looping_artifacts")
    if card["category"] != "ambience":
        tokens.add("background_noise")
    return sorted(tokens)


def compile_prompt(card: dict) -> str:
    """Build the English prompt from card tokens only.

    Every clause comes from a controlled vocabulary, so caller prose cannot be
    smuggled into the prompt through this function.
    """
    parts = [
        f"{card['size']} {card['category']} sound effect",
        f"action: {card['action']}",
    ]
    if card["materials"]:
        parts.append("material: " + ", ".join(_label(m) for m in card["materials"]))
    parts.append(f"energy: {card['energy']}")
    parts.append(f"attack: {card['attack']}")
    parts.append(f"tail: {_label(card['tail'])}")
    parts.append(f"pitch: {card['pitch']}")
    parts.append(f"brightness: {_brightness_label(card['brightness'])}")
    parts.append(f"noise ratio: {card['noise_ratio']:.3f}")
    if card["sweep"] != "none":
        parts.append(f"frequency sweep: {_label(card['sweep'])}")
    if card["frequency_hz"] is not None:
        parts.append("frequency range: " + " to ".join(f"{value:g} Hz" for value in card["frequency_hz"]))
    if card["textures"]:
        parts.append("texture: " + ", ".join(_label(t) for t in card["textures"]))
    parts.append(f"space: {_label(card['space'])}")
    parts.append(f"mood: {card['mood']}")
    parts.append("seamless loop" if card["loopable"] else "one-shot")
    if card["layer_count"] > 1:
        parts.append(f"{card['layer_count']} layers")
    if card["reference_tags"]:
        parts.append("reference: " + ", ".join(_label(t) for t in card["reference_tags"]))
    if card["must"]:
        parts.append("must include: " + ", ".join(_label(token) for token in card["must"]))
    return "; ".join(parts)


def variation_seed(seed: int, variation_index: int, digest: str) -> int:
    """Stable per-variation seed derived from the base seed and the card hash."""
    material = canonical({"card_hash": digest, "seed": seed, "variation": variation_index})
    return int(sha(material)[:8], 16)


def _generation_bounds(duration_seconds, seed, variation_index):
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
        raise CFError("invalid_spec", "duration_seconds is outside limits")
    if not math.isfinite(duration_seconds) or not 0.05 <= duration_seconds <= 12:
        raise CFError("invalid_spec", "duration_seconds is outside limits")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise CFError("invalid_spec", "seed is outside limits")
    if isinstance(variation_index, bool) or not isinstance(variation_index, int) or not 0 <= variation_index <= 7:
        raise CFError("invalid_spec", "variation_index is outside limits")


def compile_direction(
    card: dict,
    *,
    duration_seconds: float = 1.0,
    seed: int = 0,
    variation_index: int = 0,
    source_text: str | None = None,
) -> dict:
    """Compile a normalized card into a deterministic generation payload.

    ``source_text`` is only hashed for traceability; it is never used as the
    prompt.  The payload carries no model settings - those stay profile-locked.
    """
    card = validate_direction(card)
    _generation_bounds(duration_seconds, seed, variation_index)
    if source_text is not None:
        validate_source_text(source_text)

    digest = card_hash(card)
    must_not = compile_must_not(card)
    return {
        "schema_version": COMPILED_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "card": card,
        "card_hash": digest,
        "direction_present": True,
        "prompt": compile_prompt(card),
        "prompt_language": "en",
        "negative_prompt": ", ".join(_label(token) for token in must_not),
        "must_not": must_not,
        "duration_seconds": round(float(duration_seconds), 6),
        "seed": seed,
        "variation_index": variation_index,
        "variation_seed": variation_seed(seed, variation_index, digest),
        "source_text_hash": source_text_hash(source_text) if source_text is not None else None,
        "source_text_used_as_prompt": False,
    }


def compile_sfx_request(spec: dict, *, variation_index: int = 0) -> dict:
    """Compile a validated SFX request (schema v1 or v2) into a payload.

    * v2 with a ``direction`` card: the card is compiled; ``source_text`` (or a
      legacy ``prompt``) is kept as a hash only.
    * v1 / no card: the legacy prompt is the prompt, exactly as before.  It is
      reported as source text so callers can see that no card was compiled.
    """
    if not isinstance(spec, dict):
        raise CFError("invalid_spec", "An object is required")
    duration = spec.get("duration_seconds", 1)
    seed = spec.get("seed", 0)
    source = spec.get("source_text", spec.get("prompt"))
    if "direction" in spec:
        payload = compile_direction(
            spec["direction"],
            duration_seconds=duration,
            seed=seed,
            variation_index=variation_index,
            source_text=validate_source_text(source) if source is not None else None,
        )
        declared = spec.get("source_text_hash")
        if declared is not None:
            validate_source_text_hash(declared, source)
            payload["source_text_hash"] = declared
        if spec.get("negative_prompt"):
            # An explicit negative prompt augments, never replaces, the card rules.
            payload["negative_prompt"] = ", ".join(
                [payload["negative_prompt"], spec["negative_prompt"]]
            )
        return payload

    prompt = validate_source_text(source, "prompt")
    _generation_bounds(duration, seed, variation_index)
    return {
        "schema_version": COMPILED_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "card": None,
        "card_hash": None,
        "direction_present": False,
        "prompt": prompt,
        "prompt_language": "unknown",
        "negative_prompt": spec.get("negative_prompt", ""),
        "must_not": [],
        "duration_seconds": round(float(duration), 6),
        "seed": seed,
        "variation_index": variation_index,
        "variation_seed": variation_seed(seed, variation_index, sha(prompt.encode("utf-8"))),
        "source_text_hash": source_text_hash(prompt),
        "source_text_used_as_prompt": True,
    }
