import math
import struct
import wave

import pytest

from clayfarm_control.adapters.builtin import validate_spec
from clayfarm_control.adapters.stable_audio import generate
from clayfarm_control.audio import normalize_wav
from clayfarm_control.common import CFError
from clayfarm_control.registry import ADAPTERS, load_registry


def _pcm(path, *, rate=44100, channels=2, seconds=0.2):
    frames = []
    for i in range(int(rate * seconds)):
        value = 0.8 * math.sin(2 * math.pi * 440 * i / rate) if i > rate * 0.02 else 0.0
        frames.append(struct.pack("<" + "h" * channels, *([int(value * 32767)] * channels)))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels); stream.setsampwidth(2); stream.setframerate(rate)
        stream.writeframes(b"".join(frames))


def _float_wav(path):
    values = [0.0, 0.25, -0.5, 0.25]
    payload = b"".join(struct.pack("<f", x) for x in values)
    fmt = struct.pack("<HHIIHH", 3, 1, 44100, 44100 * 4, 4, 32)
    raw = b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(payload)) + b"WAVE"
    path.write_bytes(raw + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload)


def test_bgm_tracks_are_explicit_and_separate():
    lobby = {"track_id": "lobby", "prompt": "bright open welcoming melody", "duration_seconds": 8, "loop_required": True}
    preparation = {"track_id": "preparation", "prompt": "slow tense ostinato for purchasing and betting", "duration_seconds": 8, "loop_required": True}
    assert validate_spec("sa3-small-music-cpu", lobby) == lobby
    assert validate_spec("sa3-small-music-cpu", preparation) == preparation
    with pytest.raises(CFError): validate_spec("sa3-small-music-cpu", {**lobby, "track_id": "menu"})
    with pytest.raises(CFError): validate_spec("sa3-small-music-cpu", {**lobby, "event_id": "SwordHit"})


def test_sfx_contract_is_not_bgm_contract():
    spec = {"event_id": "SwordHit", "prompt": "short metallic sword impact", "duration_seconds": .4, "variation_count": 3, "seed": 7}
    assert validate_spec("sa3-small-cpu", spec) == spec
    with pytest.raises(CFError): validate_spec("sa3-small-cpu", {**spec, "track_id": "combat"})
    with pytest.raises(CFError): validate_spec("sa3-small-cpu", {**spec, "variation_count": 9})


def test_normalize_pcm_creates_master_and_review_artifacts(tmp_path):
    source = tmp_path / "source.wav"; _pcm(source)
    artifact, report = normalize_wav(source, tmp_path / "out", loop_required=True)
    assert artifact.name == "asset.wav" and artifact.stat().st_size > 44
    assert report["sample_rate"] == 44100 and report["channels"] == 2
    assert report["trimmed_leading_frames"] > 0 and report["clipping_samples"] == 0
    assert (tmp_path / "out" / "waveform.json").is_file()
    assert (tmp_path / "out" / "spectrogram.svg").read_text().startswith("<svg")
    assert (tmp_path / "out" / "audio-report.json").is_file()


def test_normalize_float32_wav(tmp_path):
    source = tmp_path / "float.wav"; _float_wav(source)
    artifact, report = normalize_wav(source, tmp_path / "out")
    with wave.open(str(artifact)) as stream:
        assert stream.getsampwidth() == 2 and stream.getframerate() == 44100
    assert report["master_format"] == "PCM_S16LE_WAV"


def test_audio_profiles_are_catalogued_without_false_readiness():
    reg = load_registry()
    assert reg["models"]["sa3-small-music"]["deployment_approved"] is False
    profiles = {p["id"]: p for p in reg["profiles"]}
    assert profiles["sa3-small-music-cpu"]["asset_kinds"] == ["music"]
    assert profiles["sa3-small-music-cpu"]["node_ready"] is False
    assert ADAPTERS["sa3-small-music-cpu"] == "stable_audio_3"
    assert "sa3-small-music-cuda" not in ADAPTERS
    assert "sa3-small-music-mlx" not in ADAPTERS


def test_neural_adapter_fails_closed_without_a_pinned_snapshot(tmp_path):
    profile = next(p for p in load_registry()["profiles"] if p["id"] == "sa3-small-music-cpu")
    with pytest.raises(CFError) as error:
        generate(profile, {"track_id": "lobby", "prompt": "test", "duration_seconds": 1}, tmp_path, tmp_path / "out")
    assert error.value.code == "audio_model_not_cached"


def test_neural_sfx_does_not_silently_drop_variations(tmp_path):
    profile = next(p for p in load_registry()["profiles"] if p["id"] == "sa3-small-cpu")
    spec = {"event_id": "SwordHit", "prompt": "short impact", "duration_seconds": .2, "variation_count": 2}
    with pytest.raises(CFError) as error:
        generate(profile, spec, tmp_path, tmp_path / "out")
    assert error.value.code == "audio_variations_not_implemented"
