"""Actual CUDA/MPS inference path; requires a pinned, separately installed env/model."""
from __future__ import annotations
from pathlib import Path
from ..common import CFError
from .builtin import validate_spec

def generate(profile,spec,model_dir: Path,out: Path):
    import os
    # Enforce failure on unsupported MPS ops; a CPU fallback is not GPU verification.
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") not in (None,"0"):
        raise CFError("cpu_fallback_forbidden","Disable implicit MPS CPU fallback")
    import torch
    from diffusers import AutoPipelineForText2Image
    pid=profile["id"]; validate_spec(pid,spec); backend=profile["backend"]; settings=profile["settings"]
    if backend=="cuda" and not torch.cuda.is_available(): raise CFError("backend_unavailable","CUDA unavailable in this environment")
    if backend=="mps" and not torch.backends.mps.is_available(): raise CFError("backend_unavailable","MPS unavailable; not falling back to CPU")
    if backend not in ("cuda","mps"): raise CFError("backend_unavailable","This adapter implements CUDA/MPS only")
    # Include the cold-load allocation peak, which may exceed inference itself.
    if backend=="cuda": torch.cuda.reset_peak_memory_stats()
    options={"variant":settings["weights_variant"]} if settings.get("weights_variant") else {}
    pipe=AutoPipelineForText2Image.from_pretrained(str(model_dir),torch_dtype=torch.float16,local_files_only=True,use_safetensors=True,**options)
    if settings.get("offload"):
        if backend!="cuda": raise CFError("unsupported_setting","This offload profile is CUDA-only")
        pipe.enable_model_cpu_offload()
    else: pipe=pipe.to(backend)
    if settings.get("vae_tiling"): pipe.enable_vae_tiling()
    if backend=="mps": pipe.enable_attention_slicing()
    turbo=pid.startswith("sd-turbo")
    out.mkdir(parents=True,exist_ok=True)
    image=pipe(prompt=spec["prompt"],generator=torch.Generator(device="cpu").manual_seed(spec.get("seed",0)),height=settings["height"],width=settings["width"],num_inference_steps=settings.get("steps",1 if turbo else 25),guidance_scale=0.0 if turbo else 7.5).images[0]
    if backend=="cuda":
        torch.cuda.synchronize(); peak=torch.cuda.max_memory_reserved()
    else:
        torch.mps.synchronize(); peak=torch.mps.driver_allocated_memory()
    if image.size!=(settings["width"],settings["height"]): raise CFError("invalid_output","Image dimensions did not match locked profile")
    path=out/"asset.png";image.save(path)
    return path,{"kind":"image_source","neural":True,"backend":backend,"torch_version":torch.__version__,"sample_device_bytes":peak,"measurement_note":"CUDA allocator peak; MPS end-of-inference sample supplemented by runner sampling. Not total system memory."}
