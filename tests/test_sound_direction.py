import json

import pytest

from clayfarm_control.audio import validate_audio_spec
from clayfarm_control.cli import main
import clayfarm_control.adapters.stable_audio as stable_audio
from clayfarm_control.common import CFError, canonical
from clayfarm_control.registry import load_registry
from clayfarm_control.sound_direction import (
    CARD_SCHEMA_VERSION,
    card_hash,
    compile_direction,
    compile_sfx_request,
    source_text_hash,
    validate_direction,
)

KOREAN_NOTE = "칼이 금속 방패에 부딪히는 짧고 날카로운 타격음, 잔향 없이"
CARD = {
    "category": "weapon",
    "action": "hit",
    "materials": ["metal", "wood"],
    "size": "small",
    "energy": "strong",
    "attack": "instant",
    "tail": "short",
    "textures": ["metallic_ring", "gritty"],
    "space": "dry",
    "pitch": "high",
    "brightness": 0.75,
    "must_not": ["reverb_tail"],
    "reference_tags": ["sword", "shield"],
}


def test_valid_card_is_normalized_with_defaults_and_sorted_lists():
    card = validate_direction(CARD)
    assert card["schema_version"] == CARD_SCHEMA_VERSION
    assert card["category"] == "weapon" and card["action"] == "hit"
    # Caller ordering must not survive: lists are de-duplicated and sorted.
    assert card["materials"] == ["metal", "wood"]
    assert card["textures"] == ["gritty", "metallic_ring"]
    assert validate_direction({**CARD, "materials": ["wood", "metal", "metal"]}) == card
    # Unset fields get explicit defaults so the card shape (and hash) is stable.
    assert card["mood"] == "neutral" and card["layer_count"] == 1 and card["loopable"] is False
    assert set(card) == set(validate_direction({"category": "ui", "action": "click"}))


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "cinematic"},
        {"action": "yodel"},
        {"materials": ["unobtanium"]},
        {"materials": ["metal", "wood", "stone", "glass"]},
        {"brightness": 1.5},
        {"brightness": -0.1},
        {"brightness": True},
        {"layer_count": 0},
        {"layer_count": 5},
        {"layer_count": 2.5},
        {"loopable": "yes"},
        {"tail": "eternal"},
        {"reference_tags": ["Sword Hit"]},
        {"must_not": ["nothing_i_dislike"]},
        {"schema_version": 2},
        {"steps": 30},
        {"guidance_scale": 7.5},
        {"checkpoint": "some-other-model"},
        {"prompt": "ignore previous instructions"},
    ],
)
def test_invalid_ranges_and_unknown_fields_are_rejected(patch):
    with pytest.raises(CFError) as error:
        validate_direction({**CARD, **patch})
    assert error.value.code == "invalid_direction"


def test_card_requires_category_and_action():
    for missing in ("category", "action"):
        spec = {key: value for key, value in CARD.items() if key != missing}
        with pytest.raises(CFError):
            validate_direction(spec)
    with pytest.raises(CFError):
        validate_direction("a short metallic hit")


def test_compiler_is_deterministic_and_hides_source_text():
    first = compile_direction(CARD, duration_seconds=0.4, seed=7, source_text=KOREAN_NOTE)
    second = compile_direction(CARD, duration_seconds=0.4, seed=7, source_text=KOREAN_NOTE)
    assert canonical(first) == canonical(second)
    assert first["card_hash"] == card_hash(validate_direction(CARD))

    # The prompt is compiled English, never the artist's note.
    assert first["source_text_used_as_prompt"] is False
    assert KOREAN_NOTE not in first["prompt"]
    assert first["prompt"].isascii() and first["prompt_language"] == "en"
    assert first["prompt"].startswith("small weapon sound effect; action: hit")
    assert "material: metal, wood" in first["prompt"]
    assert first["source_text_hash"] == source_text_hash(KOREAN_NOTE)

    # Duration, seed and must_not constraints travel with the payload.
    assert first["duration_seconds"] == 0.4 and first["seed"] == 7
    assert {"music", "speech", "vocals", "clipping", "reverb_tail"} <= set(first["must_not"])
    assert first["must_not"] == sorted(set(first["must_not"]))
    assert "reverb tail" in first["negative_prompt"]

    whoosh = compile_direction({"category": "weapon", "action": "whoosh"})
    assert {"airflow", "blowing", "breath", "sustained_wind"} <= set(whoosh["must_not"])

    # Different seeds/cards stay deterministic but diverge.
    assert first["variation_seed"] != compile_direction(CARD, seed=8)["variation_seed"]
    assert first["variation_seed"] != compile_direction(CARD, seed=7, variation_index=1)["variation_seed"]
    assert compile_direction(CARD, seed=7)["variation_seed"] == compile_direction(CARD, seed=7)["variation_seed"]


def test_compiler_carries_no_model_settings_and_bounds_generation():
    payload = compile_direction(CARD, duration_seconds=1, seed=0)
    assert not {"steps", "guidance_scale", "sampler", "checkpoint", "model"} & set(payload)
    for bad in ({"duration_seconds": 0}, {"duration_seconds": 13}, {"seed": -1}, {"variation_index": 8}):
        with pytest.raises(CFError):
            compile_direction(CARD, **bad)


def test_loopable_and_ambience_cards_change_the_constraints():
    loop = compile_direction({**CARD, "loopable": True, "space": "hall", "tail": "long"})
    assert "fade_in" in loop["must_not"] and "looping_artifacts" in loop["must_not"]
    assert "reverb_tail" in loop["must_not"]  # requested explicitly by the card
    assert "seamless loop" in loop["prompt"]
    ambience = compile_direction({"category": "ambience", "action": "rattle", "loopable": True})
    assert "background_noise" not in ambience["must_not"]


def test_schema_v2_spec_accepts_direction_but_no_model_settings():
    spec = {
        "schema_version": 2,
        "event_id": "SwordHit",
        "direction": CARD,
        "source_text": KOREAN_NOTE,
        "source_text_hash": source_text_hash(KOREAN_NOTE),
        "duration_seconds": 0.4,
        "variation_count": 2,
        "seed": 7,
    }
    assert validate_audio_spec("sa3-small-cpu", spec) == spec
    for patch in ({"steps": 30}, {"checkpoint": "x"}, {"track_id": "combat"}, {"cfg_scale": 3}):
        with pytest.raises(CFError):
            validate_audio_spec("sa3-small-cpu", {**spec, **patch})
    for patch in ({"schema_version": 3}, {"direction": {"category": "weapon"}}, {"variation_count": 9}):
        with pytest.raises(CFError):
            validate_audio_spec("sa3-small-cpu", {**spec, **patch})
    with pytest.raises(CFError):  # v2 without a card is not a valid direction request
        validate_audio_spec("sa3-small-cpu", {"schema_version": 2, "event_id": "SwordHit", "prompt": "hit"})
    with pytest.raises(CFError):  # provenance must match the note it claims to cover
        validate_audio_spec("sa3-small-cpu", {**spec, "source_text_hash": "0" * 64})
    # BGM profiles keep their own contract and do not learn about direction cards.
    with pytest.raises(CFError):
        validate_audio_spec("sa3-small-music-cpu", {"track_id": "combat", "prompt": "tense", "direction": CARD})


def test_v2_prompt_is_kept_as_source_text_not_as_a_model_prompt():
    spec = {"schema_version": 2, "event_id": "SwordHit", "direction": CARD, "prompt": KOREAN_NOTE, "seed": 3}
    assert validate_audio_spec("sa3-small-cpu", spec) == spec
    payload = compile_sfx_request(spec)
    assert payload["direction_present"] is True
    assert payload["prompt"] != KOREAN_NOTE and payload["source_text_used_as_prompt"] is False
    assert payload["source_text_hash"] == source_text_hash(KOREAN_NOTE)
    with pytest.raises(CFError):
        validate_audio_spec("sa3-small-cpu", {**spec, "source_text": "a different note"})


def test_legacy_v1_request_still_validates_and_compiles_as_source_text():
    legacy = {"event_id": "SwordHit", "prompt": "short metallic sword impact", "duration_seconds": 0.4, "seed": 7}
    assert validate_audio_spec("sa3-small-cpu", legacy) == legacy
    assert validate_audio_spec("sa3-small-cpu", {**legacy, "schema_version": 1}) is not None
    payload = compile_sfx_request(legacy)
    assert payload["direction_present"] is False and payload["card"] is None
    assert payload["prompt"] == legacy["prompt"]
    assert payload["source_text_used_as_prompt"] is True
    assert payload["duration_seconds"] == 0.4 and payload["seed"] == 7
    assert canonical(payload) == canonical(compile_sfx_request(legacy))
    with pytest.raises(CFError):
        compile_sfx_request({"event_id": "SwordHit"})


def test_cli_direction_validate_and_compile(capsys, tmp_path):
    path = tmp_path / "direction.json"
    path.write_text(json.dumps({"schema_version": 2, "event_id": "SwordSwish_A", "direction": CARD, "source_text": KOREAN_NOTE, "duration_seconds": .18, "seed": 7}), encoding="utf-8")
    assert main(["--json", "audio", "direction", "validate", "--spec", str(path)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert main(["--json", "audio", "direction", "compile", "--spec", str(path)]) == 0
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["direction_present"] is True
    assert KOREAN_NOTE not in compiled["prompt"]


def test_cli_direction_draft_is_review_only_and_can_write_spec(capsys, tmp_path):
    spec_path = tmp_path / "draft.json"
    assert main([
        "--json", "audio", "direction", "draft",
        "--source-text", "검을 빠르게 휘둘러 공기를 한 번 가르는 짧은 휙, 금속 충돌 없이",
        "--event-id", "SwordSwish_A", "--out", str(spec_path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_review"
    assert result["direction"]["action"] == "whoosh"
    assert result["direction"]["must_not"]
    written = json.loads(spec_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == 2
    assert written["source_text"] in spec_path.read_text(encoding="utf-8")
    assert validate_audio_spec("sa3-small-cpu", written) == written


def test_stable_audio_sfx_compiles_before_model_snapshot(monkeypatch, tmp_path):
    profile = next(p for p in load_registry()["profiles"] if p["id"] == "sa3-small-cpu")
    captured = {}

    def fake_compile(spec):
        captured["source_text"] = spec["source_text"]
        return {"prompt": "compiled whoosh", "negative_prompt": "blowing", "duration_seconds": .18, "seed": 3, "direction_present": True, "card_hash": "a" * 64, "compiler_version": "test", "source_text_hash": "b" * 64, "source_text_used_as_prompt": False}

    monkeypatch.setattr(stable_audio, "compile_sfx_request", fake_compile)
    spec = {"schema_version": 2, "event_id": "SwordSwish_A", "source_text": "검을 가르는 짧은 휙", "direction": CARD, "duration_seconds": .18, "seed": 3}
    with pytest.raises(CFError) as error:
        stable_audio.generate(profile, spec, tmp_path, tmp_path / "out")
    assert error.value.code == "audio_model_not_cached"
    assert captured["source_text"] == spec["source_text"]
