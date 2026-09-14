from __future__ import annotations
import importlib.resources, json
from .common import CFError, canonical, sha, safe_id
from .inventory import bands_for

# Implemented code paths, not claims of installed models or tested GPU performance.
ADAPTERS={
 "deterministic-ui":"builtin_ui", "procedural-sfx":"builtin_sfx",
 "sd-turbo-cuda":"diffusers_image", "sd-turbo-mps":"diffusers_image",
 "sdxl-lowmem-cuda":"diffusers_image", "sdxl-cuda":"diffusers_image", "sdxl-mps":"diffusers_image",
}
KINDS={"3d_model","texture","vfx","ui","sfx","rigging","animation"}

def load_registry(path=None):
    data=json.loads(path.read_text()) if path else json.loads(importlib.resources.files("clayfarm_control").joinpath("data/registry.json").read_text())
    validate_registry(data); return data

def validate_registry(reg):
    seen=set(); bands={b["id"] for b in reg["hardware_bands"]}
    for p in reg["profiles"]:
        safe_id(p["id"])
        if p["id"] in seen: raise CFError("registry_invalid","Duplicate profile")
        seen.add(p["id"])
        if p.get("model_id") and p["model_id"] not in reg["models"]: raise CFError("registry_invalid","Unknown model")
        if set(p["candidate_hardware_bands"])-bands: raise CFError("registry_invalid","Unknown hardware band")
        if set(p["asset_kinds"])-KINDS: raise CFError("registry_invalid","Unknown asset kind")
        if p.get("node_ready") is True: raise CFError("registry_invalid","A registry cannot assert readiness for an untested node")
    return reg

def get_profile(reg, profile_id):
    for p in reg["profiles"]:
        if p["id"]==profile_id: return p
    raise CFError("unknown_profile",f"Unknown profile: {profile_id}",404)

def profile_digest(reg,p):
    return sha(canonical({"profile":p,"model":reg["models"].get(p.get("model_id")),"registry_revision":reg["registry_revision"]}))

def plan(reg, inv, *, kinds=None, experimental=False, installed=None, verified_profiles=()):
    kinds=set(kinds or KINDS)
    if kinds-KINDS: raise CFError("invalid_kind","Unknown asset kind")
    bands=set(bands_for(inv)); result=[]; installed=installed or {}
    for p in reg["profiles"]:
        if not kinds.intersection(p["asset_kinds"]): continue
        reasons=[]
        if inv["os"] not in p["os_candidates"]: reasons.append("os_not_supported")
        if not bands.intersection(p["candidate_hardware_bands"]): reasons.append("outside_candidate_band")
        if p["backend"] not in inv.get("backend_candidates",["cpu"]): reasons.append("backend_not_detected")
        if p["lane"]!="candidate" and not experimental: reasons.append("experimental_opt_in_required")
        if p["id"] not in ADAPTERS: reasons.append("adapter_not_implemented")
        if p.get("model_id"): reasons.append("approved_pinned_recipe_required")
        fingerprint=profile_digest(reg,p)
        state=installed.get(p["id"],{})
        ready=bool(p["id"] in verified_profiles and p["id"] in ADAPTERS
                   and state.get("status")=="verified" and state.get("profile_digest")==fingerprint
                   and not any(r in reasons for r in ("os_not_supported","backend_not_detected","experimental_opt_in_required")))
        if ready:
            reasons=[r for r in reasons if r!="approved_pinned_recipe_required"]
        result.append({"profile_id":p["id"],"model_id":p.get("model_id"),"asset_kinds":p["asset_kinds"],"backend":p["backend"],"lane":p["lane"],"candidate":not any(r in reasons for r in ("os_not_supported","outside_candidate_band","backend_not_detected")),"adapter_implemented":p["id"] in ADAPTERS,"ready":ready,"status":"verified" if ready else "blocked" if reasons else "verification_required","blockers":reasons,"profile_digest":fingerprint})
    return {"hardware_bands":sorted(bands),"registry_revision":reg["registry_revision"],"profiles":result,"note":"Candidate != installed != verified. No device capacity guarantee."}
