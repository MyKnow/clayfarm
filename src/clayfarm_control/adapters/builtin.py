"""Restricted deterministic assets. Never labeled neural-model output."""
from __future__ import annotations
import html, math, random, re, struct, wave
from pathlib import Path
from ..common import CFError
from ..audio import AUDIO_PROFILES, validate_audio_spec

IMAGE_PROFILES={"sd-turbo-cuda","sd-turbo-mps","sdxl-lowmem-cuda","sdxl-cuda","sdxl-mps"}

def validate_spec(profile,spec):
    if not isinstance(spec,dict): raise CFError("invalid_spec","An object is required")
    if profile in AUDIO_PROFILES:
        return validate_audio_spec(profile,spec)
    if profile=="deterministic-ui":
        if set(spec)-{"text","width","height","fill","foreground","radius"}: raise CFError("invalid_spec","Unknown UI field")
        if not isinstance(spec.get("text","ClayFarm"),str) or len(spec.get("text",""))>120: raise CFError("invalid_spec","UI text max 120 characters")
        for key,default in (("width",512),("height",128)):
            if not isinstance(spec.get(key,default),int) or not 32<=spec.get(key,default)<=2048: raise CFError("invalid_spec","UI dimensions must be 32..2048")
        for k,d in (("fill","#254552"),("foreground","#ffffff")):
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}",spec.get(k,d)): raise CFError("invalid_spec","Use six-digit hexadecimal colors")
        if not isinstance(spec.get("radius",16),(int,float)) or not 0<=spec.get("radius",16)<=128: raise CFError("invalid_spec","Radius must be 0..128")
    elif profile=="procedural-sfx":
        if set(spec)-{"effect","seconds","frequency","seed"}: raise CFError("invalid_spec","Unknown SFX field")
        if spec.get("effect","beep") not in ("beep","whoosh","impact"): raise CFError("invalid_spec","Effect must be beep, whoosh, or impact")
        for key,default,low,high in (("seconds",.4,.05,5),("frequency",880,40,16000)):
            value=spec.get(key,default)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high: raise CFError("invalid_spec",f"{key} is outside limits")
        if not isinstance(spec.get("seed",0),int) or not 0<=spec.get("seed",0)<2**32: raise CFError("invalid_spec","Seed outside range")
    elif profile in IMAGE_PROFILES:
        if set(spec)-{"prompt","seed"} or not isinstance(spec.get("prompt"),str) or not 1<=len(spec["prompt"])<=2000: raise CFError("invalid_spec","Provide prompt and optional seed; dimensions/settings are profile-locked")
        if not isinstance(spec.get("seed",0),int) or not 0<=spec.get("seed",0)<2**32: raise CFError("invalid_spec","Seed outside range")
    else: raise CFError("adapter_not_implemented","No executable adapter for this profile")
    return spec

def generate(profile,spec,out: Path):
    validate_spec(profile,spec); out.mkdir(parents=True,exist_ok=True)
    if profile=="deterministic-ui":
        w,h=spec.get("width",512),spec.get("height",128)
        # Escape untrusted text. No scripts, foreignObject, URLs, fonts, or external resources.
        text=html.escape(spec.get("text","ClayFarm"),quote=True)
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" rx="{spec.get("radius",16)}" fill="{spec.get("fill","#254552")}"/><text x="{w/2}" y="{h/2}" text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-size="{min(h*.35,48)}" fill="{spec.get("foreground","#ffffff")}">{text}</text></svg>'
        path=out/"asset.svg"; path.write_text(svg,encoding="utf-8")
        return path,{"kind":"ui_source","width":w,"height":h,"neural":False,"interactive_ui":False}
    if profile=="procedural-sfx":
        rate=48000; seconds=spec.get("seconds",.4); n=int(rate*seconds); freq=spec.get("frequency",880); rng=random.Random(spec.get("seed",0)); data=bytearray(); effect=spec.get("effect","beep")
        for i in range(n):
            t=i/rate; u=i/max(1,n-1); envelope=min(1,u*30)*min(1,(1-u)*30)
            if effect=="beep": x=math.sin(2*math.pi*freq*t)*math.exp(-u*4)
            elif effect=="impact": x=(.6*rng.uniform(-1,1)+.4*math.sin(2*math.pi*freq*t))*math.exp(-u*12)
            else: x=rng.uniform(-1,1)*math.sin(math.pi*u)**2
            data+=struct.pack("<h",int(max(-.8,min(.8,.65*x*envelope))*32767))
        path=out/"asset.wav"
        with wave.open(str(path),"wb") as f: f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(data)
        return path,{"kind":"sfx","sample_rate":rate,"channels":1,"duration_seconds":seconds,"neural":False}
    raise CFError("adapter_not_implemented","Not a built-in procedural profile")
