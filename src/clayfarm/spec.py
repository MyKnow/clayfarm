from __future__ import annotations
import copy
import hashlib
import math
import re
from .util import FarmError, canonical, new_id

VIEWS = ("front", "three_quarter", "right", "back", "top", "bottom")
CLAY_PRESETS = {
    "terracotta": ([0.65, 0.22, 0.12, 1.0], 0.85),
    "cream": ([0.85, 0.72, 0.52, 1.0], 0.9),
    "sage": ([0.32, 0.48, 0.3, 1.0], 0.88),
}
ENGINES = ("sf3d", "triposr", "mock")


def validate_spec(value: dict) -> dict:
    """Reject unsupported semantics instead of pretending to edit unnamed mesh parts."""
    if not isinstance(value, dict):
        raise FarmError("spec must be a JSON object")
    allowed = {"name", "description", "height_m", "target_triangles", "pivot", "material", "axis_scale", "views", "preview_size", "geometry", "lod_ratios", "collider"}
    unknown = set(value) - allowed
    if unknown:
        raise FarmError(f"Unsupported spec fields: {sorted(unknown)}. Semantic part edits require a new concept image.")
    out = copy.deepcopy(value)
    if not isinstance(out.get("name"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", out["name"]):
        raise FarmError("name: use 1-64 ASCII letters, numbers, underscore or hyphen")
    out.setdefault("description", "")
    if not isinstance(out["description"], str) or len(out["description"]) > 3000:
        raise FarmError("description must be a string <= 3000 characters; it is review context, not executable code")
    out.setdefault("height_m", 1.0)
    if isinstance(out["height_m"], bool) or not isinstance(out["height_m"], (int, float)) or not 0.001 <= out["height_m"] <= 100:
        raise FarmError("height_m must be between 0.001 and 100")
    out.setdefault("target_triangles", 5000)
    if type(out["target_triangles"]) is not int or not 100 <= out["target_triangles"] <= 200000:
        raise FarmError("target_triangles must be an integer in [100, 200000]")
    out.setdefault("pivot", "bottom_center")
    if out["pivot"] not in ("bottom_center", "center"):
        raise FarmError("pivot: bottom_center or center")
    out.setdefault("axis_scale", [1, 1, 1])
    if (not isinstance(out["axis_scale"], list) or len(out["axis_scale"]) != 3 or
        any(type(x) not in (int, float) or not math.isfinite(x) or not 0.1 <= x <= 10 for x in out["axis_scale"])):
        raise FarmError("axis_scale must contain three numbers between 0.1 and 10 (Blender XYZ)")
    out.setdefault("material", {"mode": "preserve"})
    mat = out["material"]
    if not isinstance(mat, dict) or set(mat) - {"mode", "color", "roughness", "preset"}:
        raise FarmError("material accepts mode/color/roughness only")
    if "preset" in mat:
        if not isinstance(mat["preset"], str) or mat["preset"] not in CLAY_PRESETS:
            raise FarmError(f"material.preset must be one of {tuple(CLAY_PRESETS)}")
        color, roughness = CLAY_PRESETS[mat["preset"]]
        mat.setdefault("mode", "clay_single")
        mat.setdefault("color", color.copy()); mat.setdefault("roughness", roughness)
    mat.setdefault("mode", "preserve")
    if mat["mode"] not in ("preserve", "clay_single"):
        raise FarmError("material.mode: preserve or clay_single")
    mat.setdefault("color", [0.8, 0.25, 0.15, 1.0])
    if not isinstance(mat["color"], list) or len(mat["color"]) != 4 or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in mat["color"]):
        raise FarmError("material.color must contain four RGBA values in [0,1]")
    mat.setdefault("roughness", 0.85)
    if type(mat["roughness"]) not in (int, float) or not 0 <= mat["roughness"] <= 1:
        raise FarmError("roughness must be in [0,1]")
    out.setdefault("views", list(VIEWS))
    if not isinstance(out["views"], list) or not 1 <= len(out["views"]) <= 6 or any(not isinstance(v, str) or v not in VIEWS for v in out["views"]) or len(set(out["views"])) != len(out["views"]):
        raise FarmError(f"views must be a nonempty unique subset of {VIEWS}")
    out.setdefault("preview_size", 384)
    if type(out["preview_size"]) is not int or not 128 <= out["preview_size"] <= 768:
        raise FarmError("preview_size must be an integer in [128,768]")
    geo = out.setdefault("geometry", {})
    if not isinstance(geo, dict) or set(geo) - {"remesh", "voxel_size_ratio", "merge_distance_ratio", "smooth_iterations", "shade_smooth"}:
        raise FarmError("Unsupported geometry options")
    geo.setdefault("remesh", "none")
    if geo["remesh"] not in ("none", "voxel"):
        raise FarmError("geometry.remesh: none or voxel")
    for key, default, low, high in (("voxel_size_ratio", .02, .005, .1), ("merge_distance_ratio", .00001, 0, .001)):
        val = geo.setdefault(key, default)
        if type(val) not in (int, float) or not math.isfinite(val) or not low <= val <= high:
            raise FarmError(f"geometry.{key} must be in [{low},{high}]")
    val = geo.setdefault("smooth_iterations", 0)
    if type(val) is not int or not 0 <= val <= 10: raise FarmError("smooth_iterations must be in [0,10]")
    if type(geo.setdefault("shade_smooth", True)) is not bool: raise FarmError("shade_smooth must be boolean")
    if geo["remesh"] == "voxel" and mat["mode"] != "clay_single":
        raise FarmError("Voxel remesh requires clay_single: source UV/material preservation is not supported")
    ratios = out.setdefault("lod_ratios", [])
    if (not isinstance(ratios, list) or len(ratios) > 3 or
        any(type(x) not in (int, float) or not math.isfinite(x) or not .05 <= x < 1 for x in ratios) or
        any(a <= b for a, b in zip(ratios, ratios[1:]))):
        raise FarmError("lod_ratios: up to 3 strictly decreasing values in [0.05,1)")
    if out.setdefault("collider", "none") not in ("none", "box", "convex_hull"):
        raise FarmError("collider: none, box or convex_hull")
    return out


def plan(job_id: str, spec: dict, concepts: list[dict], engines: list[str], *, raw_mesh: dict | None = None) -> list[dict]:
    if not engines or any(e not in ENGINES for e in engines) or len(engines) != len(set(engines)):
        raise FarmError(f"Choose distinct engines from {ENGINES}; duplicate seeds are not useful candidates")
    if raw_mesh is None and not 1 <= len(concepts) <= 4:
        raise FarmError("Provide 1-4 concept images")
    branches = [(i, image, engine) for i, image in enumerate(concepts) for engine in engines] if raw_mesh is None else [(0, raw_mesh, "revision")]
    if len(branches) > 4:
        raise FarmError("v1 allows at most 4 meaningful candidates per job")
    tasks = []
    seen = set()
    for index, blob, engine in branches:
        marker = (blob["sha256"], engine)
        if marker in seen:
            continue
        seen.add(marker)
        candidate = f"{index+1}-{engine}"
        parent = None
        if raw_mesh is None:
            parent = new_id()
            tasks.append({"id": parent, "job_id": job_id, "kind": "reconstruct", "capability": engine, "slot": "gpu", "parent_id": None,
                          "priority": 80, "payload": {"candidate": candidate, "engine": engine, "input": blob, "spec": spec}})
        process_id = new_id()
        tasks.append({"id": process_id, "job_id": job_id, "kind": "process", "capability": "mock" if engine == "mock" else "blender", "slot": "cpu", "parent_id": parent,
                      "priority": 90, "payload": {"candidate": candidate, "spec": spec, **({"input": raw_mesh} if raw_mesh else {})}})
        for view in spec["views"]:
            tasks.append({"id": new_id(), "job_id": job_id, "kind": "preview", "capability": "mock" if engine == "mock" else "blender", "slot": "cpu", "parent_id": process_id,
                          "priority": 100, "payload": {"candidate": candidate, "view": view, "spec": spec}})
    return tasks


def task_fingerprint(task: dict) -> str:
    # Attempt and worker IDs are intentionally excluded; canonical inputs are immutable.
    material = {k: task.get(k) for k in ("id", "kind", "capability", "payload", "parent_output")}
    return hashlib.sha256(canonical(material).encode()).hexdigest()
