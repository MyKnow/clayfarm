"""Inventory only: nominal hardware bands never establish model readiness."""
from __future__ import annotations
import csv, io, json, platform, shutil, subprocess, sys
from pathlib import Path
import psutil
from .common import now
GIB=1024**3

def run_probe(argv, timeout=10):
    try:
        r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=True)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError): return None

def capacity_band(gib: float, apple=False):
    bins=(16,24,32) if apple else (4,6,8,12,16,24,32)
    # A small reporting tolerance handles driver-reserved framebuffer; NOT admission.
    eligible=[n for n in bins if gib >= n*.96]
    return ("A" if apple else "C")+str(max(eligible)) if eligible else None

def bands_for(inv: dict) -> list[str]:
    bands=["CPU"]
    for device in inv.get("devices",[]):
        if device.get("backend")=="cuda" and device.get("total_bytes"):
            b=capacity_band(device["total_bytes"]/GIB)
            if b: bands.append(b)
    if inv.get("memory_kind")=="unified" and inv.get("ram_total_bytes"):
        b=capacity_band(inv["ram_total_bytes"]/GIB,True)
        if b: bands.append(b)
    return sorted(set(bands))

def probe(*, python: str|None=None, deep=False) -> dict:
    system=platform.system(); memory=psutil.virtual_memory()
    apple=system=="Darwin" and platform.machine().lower() in ("arm64","aarch64")
    devices=[]
    raw=run_probe(["nvidia-smi","--query-gpu=uuid,name,memory.total,memory.free,utilization.gpu,temperature.gpu","--format=csv,noheader,nounits"]) if shutil.which("nvidia-smi") else None
    if raw:
        for row in csv.reader(io.StringIO(raw)):
            try:
                dev,name,total,free,util,temp=[s.strip() for s in row]
                devices.append({"id":dev,"name":name,"backend":"cuda","total_bytes":int(total)*1024**2,"free_bytes":int(free)*1024**2,"utilization_percent":float(util),"temperature_c":float(temp),"runtime_verified":False})
            except (ValueError,TypeError): continue
    backends=["cpu"]
    if devices: backends.append("cuda")
    if apple: backends += ["mps","mlx"]
    runtime={}
    if deep:
        # Probe in the selected isolated environment, not in the lightweight CLI process.
        script="""import json,importlib.util
r={}
try:
 import torch
 r['torch_version']=torch.__version__
 r['cuda']=torch.cuda.is_available()
 r['mps']=bool(hasattr(torch.backends,'mps') and torch.backends.mps.is_available())
 if r['mps']: r['mps_recommended_bytes']=torch.mps.recommended_max_memory()
except ImportError: pass
try:
 import mlx.core as mx
 r['mlx']=bool(mx.metal.is_available())
except (ImportError,AttributeError): r['mlx']=False
print(json.dumps(r))
"""
        raw=run_probe([python or sys.executable,"-c",script],30)
        if raw:
            try: runtime=json.loads(raw.splitlines()[-1])
            except ValueError: runtime={}
    try:
        battery=psutil.sensors_battery(); on_battery=bool(battery and not battery.power_plugged)
    except (OSError,psutil.Error,AttributeError):
        on_battery=None
    inv={"schema_version":1,"captured_at":now(),"os":{"Darwin":"macos","Windows":"windows"}.get(system,system.lower()),"arch":platform.machine(),"cpu_count":psutil.cpu_count(logical=True),"memory_kind":"unified" if apple else "host_plus_dedicated","ram_total_bytes":memory.total,"ram_available_bytes":memory.available,"memory_pressure_percent":memory.percent,"on_battery":on_battery,"devices":devices,"backend_candidates":backends,"runtime":runtime,"disk_free_bytes":shutil.disk_usage(Path.home()).free}
    inv["hardware_bands"]=bands_for(inv)
    return inv

def memory_admission(inv: dict, evidence: dict, backend: str, *, safety=1.2, reserve_bytes=2*GIB) -> tuple[bool,str]:
    """Admission is conservative and separate from matching. Unknown is not zero."""
    host=evidence.get("peak_host_bytes"); device=evidence.get("peak_device_bytes")
    if host is None or (backend!="cpu" and device is None): return False,"memory_measurement_missing"
    host_available=inv.get("ram_available_bytes")
    if host_available is None: return False,"host_memory_unknown"
    if inv.get("memory_kind")=="unified":
        # Sum conservatively: samples may overlap, but never reserve two independent pools.
        need=(host+(device or 0))*safety+reserve_bytes
        if need>host_available: return False,"unified_memory_pressure"
        recommended=inv.get("runtime",{}).get("mps_recommended_bytes")
        if backend=="mps" and recommended is None: return False,"mps_budget_unknown"
        if recommended is not None and (device or 0)*safety>recommended: return False,"mps_recommended_limit"
    else:
        if host*safety+reserve_bytes>host_available: return False,"host_memory_pressure"
        if backend=="cuda":
            candidates=[d for d in inv.get("devices",[]) if d.get("backend")=="cuda"]
            # v0.3 uses a selected physical device; do not sum VRAM across devices.
            selected=evidence.get("device_id")
            if selected: candidates=[d for d in candidates if d.get("id")==selected]
            if not candidates or candidates[0].get("free_bytes",0)<device*safety+512*1024**2: return False,"device_memory_pressure"
    return True,"within_measured_budget"
