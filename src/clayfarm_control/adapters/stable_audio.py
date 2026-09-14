"""Stable Audio 3 local adapter.

The adapter imports the pinned model runtime inside the isolated model
process.  Missing packages, weights, or a backend fail closed; there is no
procedural or hosted fallback that could be mistaken for neural output.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from ..audio import AUDIO_PROFILES, normalize_wav, validate_audio_spec
from ..common import CFError


def _device(profile):
    backend = profile.get("backend")
    if backend == "cpu":
        return "cpu"
    if backend == "cuda":
        try:
            import torch
            if not torch.cuda.is_available():
                raise CFError("backend_unavailable", "CUDA is unavailable in the selected runtime")
        except ImportError as exc:
            raise CFError("runtime_not_installed", "The selected runtime does not include PyTorch") from exc
        return "cuda"
    if backend == "mps":
        try:
            import torch
            if not hasattr(torch.backends, "mps") or not torch.backends.mps.is_available():
                raise CFError("backend_unavailable", "MPS is unavailable in the selected runtime")
        except ImportError as exc:
            raise CFError("runtime_not_installed", "The selected runtime does not include PyTorch") from exc
        return "mps"
    # The official Stable Audio 3 repository has a separate MLX route.  It is
    # intentionally not silently routed through PyTorch/MPS.
    raise CFError("backend_unavailable", "This Stable Audio adapter has no verified MLX runner yet")


def generate(profile: dict, spec: dict, model_dir: Path, out: Path):
    profile_id = profile.get("id", "")
    if profile_id not in AUDIO_PROFILES:
        raise CFError("adapter_not_implemented", "No executable audio profile")
    validate_audio_spec(profile_id, spec)
    if profile_id.startswith("sa3-small-") and not profile_id.startswith("sa3-small-music") and spec.get("variation_count", 1) != 1:
        raise CFError("audio_variations_not_implemented", "Generate one SFX variation per job until the bundle artifact contract is enabled")
    device = _device(profile)
    model_dir = Path(model_dir)
    if not model_dir.is_dir() or model_dir.resolve() == Path(".").resolve() or not any(model_dir.iterdir()):
        raise CFError("audio_model_not_cached", "A verified local Stable Audio model snapshot is required")
    try:
        stable_audio = importlib.import_module("stable_audio_3")
    except ImportError as exc:
        raise CFError("runtime_not_installed", "Install the pinned stable-audio-3 runtime before verification") from exc
    model_cls = getattr(stable_audio, "StableAudioModel", None)
    if model_cls is None:
        raise CFError("runtime_not_installed", "StableAudioModel is missing from the pinned runtime")
    settings = profile.get("settings", {})
    model_name = settings.get("model_name")
    if not isinstance(model_name, str) or not model_name:
        raise CFError("profile_invalid", "Stable Audio model_name is not locked in the profile")
    config_path = next(model_dir.rglob("model_config.json"), None)
    checkpoint_path = next(model_dir.rglob("model.safetensors"), None)
    if not config_path or not checkpoint_path:
        raise CFError("audio_model_files_missing", "The local snapshot must contain model_config.json and model.safetensors")
    try:
        # Stable Audio's public API resolves a model identifier through
        # huggingface_hub. Replace that resolver for this child process with
        # the already hash-verified release directory so offline workers never
        # download an unpinned checkpoint.
        configs = importlib.import_module("stable_audio_3.model_configs")
        all_models = getattr(configs, "all_models")
        original_config = all_models.get(model_name)
        if original_config is None:
            raise CFError("profile_invalid", f"Unknown Stable Audio model: {model_name}")
        class LocalConfig:
            def resolve(self):
                return str(config_path), str(checkpoint_path)
        all_models[model_name] = LocalConfig()
        try:
            model = model_cls.from_pretrained(model_name, device=device)
        finally:
            all_models[model_name] = original_config
        kwargs = {
            "prompt": spec["prompt"],
            "duration": float(spec.get("duration_seconds", settings.get("duration_seconds", 5))),
            "seed": int(spec.get("seed", 0)),
            "steps": int(settings.get("steps", 8)),
        }
        if "negative_prompt" in spec:
            kwargs["negative_prompt"] = spec["negative_prompt"]
        if "cfg_scale" in settings:
            kwargs["cfg_scale"] = float(settings["cfg_scale"])
        audio = model.generate(**kwargs)
    except CFError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise CFError("audio_generation_failed", "Stable Audio generation failed in the isolated runtime") from exc
    try:
        import torch
        import torchaudio
    except ImportError as exc:
        raise CFError("runtime_not_installed", "The pinned runtime needs torch and torchaudio") from exc
    try:
        if not isinstance(audio, torch.Tensor):
            raise TypeError("model output is not a tensor")
        if audio.ndim == 3:
            audio = audio[0]
        if audio.ndim == 1:
            audio = audio.unsqueeze(0)
        if audio.ndim != 2 or audio.shape[0] not in (1, 2):
            raise ValueError("expected mono or stereo tensor")
        raw = Path(out) / "_stable-audio-raw.wav"
        Path(out).mkdir(parents=True, exist_ok=True)
        # Match the official CLI's backend-neutral save call. The post-
        # processor accepts either float32 or PCM input and writes the Unity
        # master in one controlled format.
        torchaudio.save(str(raw), audio.detach().to("cpu"), 44100)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise CFError("audio_output_failed", "Stable Audio returned an unsupported audio tensor") from exc
    artifact, report = normalize_wav(raw, out, loop_required=bool(spec.get("loop_required", False)))
    try:
        raw.unlink()
    except OSError:
        pass
    details = {
        "kind": "bgm" if profile_id.startswith("sa3-small-music") else "sfx",
        "neural": True,
        "model": model_name,
        "backend": profile.get("backend"),
        "track_id": spec.get("track_id"),
        "event_id": spec.get("event_id"),
        "seed": spec.get("seed", 0),
        "audio_report": report,
    }
    return artifact, details
