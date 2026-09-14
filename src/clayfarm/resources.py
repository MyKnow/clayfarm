from __future__ import annotations
import ctypes
import hashlib
import importlib.resources
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from .util import read_json
from . import __version__


def probe(argv):
    try:
        return subprocess.run(argv,capture_output=True,text=True,timeout=8,check=True).stdout.strip()
    except (OSError,subprocess.SubprocessError): return None


def gpu_stats():
    if not shutil.which("nvidia-smi"): return None
    raw=probe(["nvidia-smi","--query-gpu=name,memory.total,memory.free,utilization.gpu,temperature.gpu","--format=csv,noheader,nounits"])
    if not raw: return None
    try:
        # v1 uses one accelerator per machine; do not silently spread into other people's GPUs.
        name,total,free,util,temp=[s.strip() for s in raw.splitlines()[0].split(",")]
        return {"name":name,"total_mb":int(total),"free_mb":int(free),"utilization":int(util),"temperature":int(temp)}
    except (ValueError,IndexError): return None


def memory_available_mb():
    try:
        if os.name=="nt":
            class Mem(ctypes.Structure):
                _fields_=[("length",ctypes.c_ulong),("load",ctypes.c_ulong)]+[(x,ctypes.c_ulonglong) for x in ("total","avail","total_page","avail_page","total_virtual","avail_virtual","extended")]
            s=Mem(); s.length=ctypes.sizeof(s)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)): return s.avail//(1024*1024)
        elif platform.system()=="Linux":
            text=Path("/proc/meminfo").read_text()
            return int(re.search(r"MemAvailable:\s+(\d+)",text).group(1))//1024
        elif platform.system()=="Darwin":
            raw=probe(["vm_stat"])
            page=int(re.search(r"page size of (\d+) bytes",raw).group(1))
            # Conservative: exclude compressed/purgeable memory. This is not free CUDA VRAM.
            count=sum(int(re.search(rf"{k}:\s+(\d+)",raw).group(1)) for k in ("Pages free","Pages inactive"))
            return count*page//(1024*1024)
    except (OSError,ValueError,AttributeError,TypeError): pass
    return None


def on_battery():
    if platform.system()=="Darwin":
        raw=probe(["pmset","-g","batt"])
        return "Battery Power" in raw if raw else None
    if os.name=="nt":
        class Power(ctypes.Structure):
            _fields_=[("ac",ctypes.c_ubyte),("flags",ctypes.c_ubyte),("percent",ctypes.c_ubyte),("reserved",ctypes.c_ubyte),("life",ctypes.c_ulong),("full",ctypes.c_ulong)]
        p=Power()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p)): return p.ac==0 if p.ac!=255 else None
    return None


def blender_path(cfg):
    if cfg.get("blender") and Path(cfg["blender"]).is_file(): return str(Path(cfg["blender"]).resolve())
    found=shutil.which("blender")
    if found: return found
    if platform.system()=="Darwin":
        path=Path("/Applications/Blender.app/Contents/MacOS/Blender")
        if path.is_file(): return str(path)
    if os.name=="nt":
        base=Path(os.environ.get("ProgramFiles","C:/Program Files"))/"Blender Foundation"
        for p in sorted(base.glob("Blender */blender.exe"),reverse=True): return str(p)
    return None


def blender_signature(cfg):
    path=blender_path(cfg)
    if not path: return None
    stat=Path(path).stat()
    adapter=importlib.resources.files("clayfarm").joinpath("blender_script.py").read_bytes()
    return hashlib.sha256(adapter+f"{path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


def blender_ready(cfg):
    sig=blender_signature(cfg)
    return bool(sig and cfg.get("blender_selftest",{}).get("signature")==sig)


def capabilities(cfg):
    caps=[]
    if blender_ready(cfg): caps.append("blender")
    if gpu_stats():
        for engine in ("sf3d","triposr"):
            r=cfg.get("engines",{}).get(engine,{})
            if r.get("ready") and Path(r.get("python","")).is_file() and (Path(r.get("repo",""))/"run.py").is_file(): caps.append(engine)
    if cfg.get("allow_mock",False): caps.append("mock")
    return caps


def telemetry(cfg):
    return {"platform":platform.system(),"arch":platform.machine(),"gpu":gpu_stats(),"memory_available_mb":memory_available_mb(),
            "on_battery":on_battery(),"paused":(Path(cfg["home"])/"PAUSED").exists(),"version":__version__}


def can_run(slot,cfg,stats):
    if stats.get("paused"): return False
    if stats.get("on_battery") and not cfg.get("allow_battery",False): return False
    memory=stats.get("memory_available_mb")
    need=cfg.get("gpu_min_ram_mb",8000) if slot=="gpu" else cfg.get("cpu_min_ram_mb",3000)
    if memory is not None and memory<need: return False
    if slot=="gpu":
        if cfg.get("allow_mock"): return True
        g=stats.get("gpu")
        return bool(g and g["free_mb"]>=cfg.get("min_free_vram_mb",7000)
                    and g["utilization"]<=cfg.get("max_external_gpu_util",20)
                    and g["temperature"]<cfg.get("max_gpu_temperature",85))
    return True
