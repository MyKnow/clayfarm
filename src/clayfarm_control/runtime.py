"""Isolated entry point used by the model manager; no network during generation."""
from __future__ import annotations
import argparse, json, os, threading, time
from pathlib import Path
from .common import atomic_json, file_sha, now, CFError

def execute(profile,spec,model_dir,out,runtime_python=None):
    import psutil
    from .registry import ADAPTERS
    adapter=ADAPTERS.get(profile["id"])
    samples={"peak_host_bytes":0,"peak_device_bytes":0 if profile["backend"]=="cpu" else None}
    stop=threading.Event(); proc=psutil.Process(); backend=profile["backend"]
    def measure():
        while not stop.wait(.05):
            try:
                samples["peak_host_bytes"]=max(samples["peak_host_bytes"],proc.memory_info().rss)
                import sys
                torch=sys.modules.get("torch")
                if torch and backend=="mps" and torch.backends.mps.is_available():
                    samples["peak_device_bytes"]=max(samples["peak_device_bytes"] or 0,torch.mps.driver_allocated_memory())
                elif torch and backend=="cuda" and torch.cuda.is_available():
                    samples["peak_device_bytes"]=max(samples["peak_device_bytes"] or 0,torch.cuda.memory_reserved())
            except (AttributeError,RuntimeError,psutil.Error): pass
    t=threading.Thread(target=measure,daemon=True); t.start(); started=time.monotonic()
    try:
        if adapter in ("builtin_ui","builtin_sfx"):
            from .adapters.builtin import generate
            artifact,details=generate(profile["id"],spec,out)
        elif adapter=="diffusers_image":
            from .adapters.diffusers_image import generate
            artifact,details=generate(profile,spec,model_dir,out)
        elif adapter=="stable_audio_3":
            from .adapters.stable_audio import generate
            artifact,details=generate(profile,spec,model_dir,out)
        else: raise CFError("adapter_not_implemented","No executable adapter")
        samples["peak_host_bytes"]=max(samples["peak_host_bytes"],proc.memory_info().rss)
        if details.get("sample_device_bytes") is not None: samples["peak_device_bytes"]=max(samples["peak_device_bytes"] or 0,details["sample_device_bytes"])
        return {"status":"verified","backend":backend,"tested_at":now(),"artifact":str(artifact.resolve()),"artifact_sha256":file_sha(artifact),"artifact_size":artifact.stat().st_size,"duration_seconds":time.monotonic()-started,"details":details,**samples}
    except Exception as exc:
        exc.runtime_samples={**samples,'duration_seconds':time.monotonic()-started}
        raise
    finally: stop.set();t.join(timeout=2)

def main():
    parser=argparse.ArgumentParser();parser.add_argument("request");parser.add_argument("result");args=parser.parse_args()
    req=json.loads(Path(args.request).read_text())
    try:
        if req['profile']['backend']=='mps' and req.get('device_budget_bytes'):
            import torch
            if not torch.backends.mps.is_available(): raise CFError('backend_unavailable','MPS is unavailable')
            torch.mps.set_per_process_memory_fraction(min(1.0,req['device_budget_bytes']/torch.mps.recommended_max_memory()))
        if req['profile']['backend']=='cuda' and req.get('device_budget_bytes'):
            import torch
            if not torch.cuda.is_available():raise CFError('backend_unavailable','CUDA is unavailable')
            torch.cuda.set_per_process_memory_fraction(min(1.0,req['device_budget_bytes']/torch.cuda.get_device_properties(0).total_memory))
        result=execute(req["profile"],req["spec"],Path(req.get("model_dir",".")),Path(req["out"]),req.get("runtime_python"))
        atomic_json(Path(args.result),result)
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()  # Isolated local log; never returned by the public API.
        oom='out of memory' in str(e).lower()
        code=e.code if isinstance(e,CFError) else 'device_memory_pressure' if oom else 'runtime_failed'
        message=e.message if isinstance(e,CFError) else 'Device memory budget exceeded; model remains unverified' if oom else 'Model execution failed; inspect local runtime.log'
        atomic_json(Path(args.result),{"status":"failed","code":code,"message":message,**getattr(e,'runtime_samples',{})})
        return 1
if __name__=="__main__": raise SystemExit(main())
