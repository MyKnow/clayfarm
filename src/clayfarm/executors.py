from __future__ import annotations
import contextlib
import importlib.resources
import json
import os
import signal
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from . import __version__
from .png import encode
from .mesh_coordinates import triposr_to_gltf, CONTRACT as MESH_COORDINATE_CONTRACT
from .resources import blender_path
from .spec import validate_spec
from .util import FarmError, atomic_bytes, read_json, write_json


def terminate_tree(proc):
    if proc.poll() is not None: return
    if os.name=="nt":
        subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],capture_output=True,timeout=15,check=False)
    else:
        with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid,signal.SIGTERM)
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid,signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired): proc.wait(timeout=10)


def run(argv: list[str],cwd: Path,log: Path,timeout: int,cancel: threading.Event,extra_env=None):
    env=os.environ.copy(); env.update(extra_env or {})
    # Local package credentials are never placed in executor command arguments/environment.
    for key in list(env):
        if key.startswith(('SUPABASE_','CLAYFARM_')) or key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
            env.pop(key,None)
    flags={"creationflags":subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=="nt" else {"start_new_session":True}
    with log.open("wb") as output:
        proc=subprocess.Popen(argv,cwd=cwd,stdout=output,stderr=subprocess.STDOUT,env=env,shell=False,**flags)
        started=time.monotonic()
        try:
            while proc.poll() is None:
                if cancel.wait(0.25): raise FarmError("Execution cancelled after lease loss or user cancellation")
                if time.monotonic()-started>timeout: raise FarmError("Executor time budget exceeded")
            if proc.returncode:
                raise FarmError(f"Executor failed (exit={proc.returncode}); inspect local task.log, not the entire agent context")
        finally:
            terminate_tree(proc)


def mock_glb() -> bytes:
    """A synthetic tetrahedron, never presented as generated AI output."""
    vertices=[(-0.5,0,-0.5),(0.5,0,-0.5),(0,0,0.5),(0,1,0)]
    indices=[0,2,1,0,1,3,1,2,3,2,0,3]
    buf=b"".join(struct.pack("<fff",*v) for v in vertices)+struct.pack("<12H",*indices)
    doc={"asset":{"version":"2.0","generator":"ClayFarm MOCK fixture - NOT AI generated"},"scene":0,"scenes":[{"nodes":[0]}],"nodes":[{"mesh":0}],
         "meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1}]}],"buffers":[{"byteLength":len(buf)}],
         "bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":48,"target":34962},{"buffer":0,"byteOffset":48,"byteLength":24,"target":34963}],
         "accessors":[{"bufferView":0,"componentType":5126,"count":4,"type":"VEC3","min":[-.5,0,-.5],"max":[.5,1,.5]},
                      {"bufferView":1,"componentType":5123,"count":12,"type":"SCALAR"}]}
    js=json.dumps(doc,separators=(",",":")).encode(); js+=b" "*((-len(js))%4); buf+=b"\0"*((-len(buf))%4)
    return struct.pack("<4sII",b"glTF",2,12+8+len(js)+8+len(buf))+struct.pack("<I4s",len(js),b"JSON")+js+struct.pack("<I4s",len(buf),b"BIN\0")+buf


def execute(task: dict,input_path: Path,work: Path,cfg: dict,cancel: threading.Event) -> dict:
    work=work.resolve(); input_path=input_path.resolve()
    work.mkdir(parents=True,exist_ok=True)
    spec=validate_spec(task["payload"]["spec"])
    kind=task["kind"]; started=time.monotonic()
    if kind not in ("reconstruct","process","preview"): raise FarmError("Unknown task kind")
    provenance={"worker_version":__version__,"capability":task["capability"],"kind":kind}
    if task["capability"]=="mock":
        if not cfg.get("allow_mock"): raise FarmError("Mock execution must be explicitly enabled")
        if cfg.get("mock_delay"): cancel.wait(cfg["mock_delay"])
        if cancel.is_set(): raise FarmError("cancelled")
        if kind=="preview":
            n=128; pixels=bytearray([245,240,225,255])*(n*n)
            # Red diagonal watermark pattern distinguishes fixtures from real asset previews.
            for y in range(n):
                for x in range(n):
                    if (x+y)%24<4 or (40<x<88 and 24<y<104): pixels[(y*n+x)*4:(y*n+x)*4+4]=bytes([190,40,40,255])
            atomic_bytes(work/"preview.png",encode(n,n,bytes(pixels)))
            files=[{"role":"preview","local":str(work/"preview.png"),"name":"preview.png"}]; metrics={"mock":True}
        else:
            atomic_bytes(work/"mesh.glb",mock_glb()); files=[{"role":"mesh","local":str(work/"mesh.glb"),"name":"mesh.glb"}]
            metrics={"hard_pass":False,"triangles":4,"warning":"MOCK fixture: no AI generation, no measured visual quality"}
        return {"files":files,"metrics":metrics,"mock":True,"provenance":provenance}
    if kind=="reconstruct":
        engine=task["payload"]["engine"]; setup=cfg.get("engines",{}).get(engine,{})
        if not setup.get("ready"): raise FarmError(f"Engine {engine} must pass warm/self-test before it can claim work")
        repo=Path(setup["repo"]).resolve(); python=str(Path(setup["python"]).resolve())
        out=work/"reconstruction"; out.mkdir(exist_ok=True)
        argv=[python,str(repo/"run.py"),str(input_path),"--output-dir",str(out)]
        if engine=="sf3d":
            argv += ["--device","cuda","--texture-resolution","1024","--remesh_option","none"]
            if setup.get("model_dir"): argv += ["--pretrained-model",setup["model_dir"]]
        elif engine=="triposr":
            argv += ["--device","cuda:0","--model-save-format","glb","--chunk-size","4096","--mc-resolution","256"]
            if setup.get("model_dir"): argv += ["--pretrained-model-name-or-path",setup["model_dir"]]
        else: raise FarmError("Unsupported reconstruction engine")
        run(argv,repo,work/"task.log",cfg.get("executor_timeout",1800),cancel,{"OMP_NUM_THREADS":str(cfg.get("cpu_threads",2)),"HF_HUB_OFFLINE":"1" if setup.get("offline_ready") else "0"})
        path=out/"0"/"mesh.glb"
        if not path.is_file() or path.read_bytes()[:4]!=b"glTF": raise FarmError("Reconstruction did not produce expected 0/mesh.glb")
        if engine=="triposr":
            atomic_bytes(path,triposr_to_gltf(path.read_bytes()))
            provenance.update(source_up_axis="Z",mesh_up_axis="Y",coordinate_contract=MESH_COORDINATE_CONTRACT)
        provenance.update({k:setup[k] for k in ("git_commit","model_revision") if k in setup})
        return {"files":[{"role":"mesh","local":str(path),"name":"mesh.glb"}],"metrics":{},"mock":False,"provenance":provenance}
    blender=blender_path(cfg)
    if not blender: raise FarmError("Blender is not installed or configured")
    # A reused selftest/task directory must not turn stale files into a success.
    for name in ("mesh.glb","mesh.fbx","metrics.json","preview.png","lod1.glb","lod2.glb","lod3.glb","collider.glb"):
        (work/name).unlink(missing_ok=True)
    # Blender's import/export path handling does not accept Windows extended paths.
    # Stage disposable compute in a short OS temp path, then copy into the durable outbox.
    with tempfile.TemporaryDirectory(prefix="cf-") as temporary:
        stage=Path(temporary); source=stage/"input.glb"
        shutil.copyfile(input_path,source)
        parent_provenance=(task.get('parent_output') or {}).get('provenance') or {}
        if kind=='process' and parent_provenance.get('capability')=='triposr' and parent_provenance.get('kind')=='reconstruct':
            # Old workers published raw Z-up. New outputs carry an idempotent
            # marker; previews and CPU revisions already use standard glTF.
            atomic_bytes(source,triposr_to_gltf(source.read_bytes()))
            provenance['input_coordinate_contract']=MESH_COORDINATE_CONTRACT
        script=stage/"adapter.py"
        atomic_bytes(script,importlib.resources.files("clayfarm").joinpath("blender_script.py").read_bytes())
        params={"kind":kind,"spec":spec,"input":str(source),"output":str(stage),"view":task["payload"].get("view"),"cpu_threads":cfg.get("cpu_threads",2)}
        write_json(stage/"parameters.json",params)
        try:
            run([blender,"--background","--factory-startup","--disable-autoexec","--python-exit-code","1","--threads",str(cfg.get("cpu_threads",2)),"--python",str(script),"--",str(stage/"parameters.json")],
                stage,stage/"task.log",cfg.get("executor_timeout",1800),cancel)
            for name in ("mesh.glb","mesh.fbx","metrics.json","preview.png","lod1.glb","lod2.glb","lod3.glb","collider.glb"):
                if (stage/name).is_file(): atomic_bytes(work/name,(stage/name).read_bytes())
        finally:
            if (stage/"task.log").is_file(): shutil.copyfile(stage/"task.log",work/"task.log")
    if kind=="process":
        files=[{"role":role,"local":str(work/name),"name":name} for role,name in (("mesh","mesh.glb"),("unity_mesh","mesh.fbx"),("metrics","metrics.json"))]
        metrics=read_json(work/"metrics.json",{})
        if not isinstance(metrics.get("hard_pass"), bool): raise FarmError("Missing measured Blender checks")
        for index in range(1,len(spec["lod_ratios"])+1):
            name=f"lod{index}.glb"; files.append({"role":"lod","local":str(work/name),"name":name})
        if spec["collider"]!="none": files.append({"role":"collider","local":str(work/"collider.glb"),"name":"collider.glb"})
    else:
        files=[{"role":"preview","local":str(work/"preview.png"),"name":"preview.png"}]; metrics={"view":task["payload"]["view"]}
    for f in files:
        if not Path(f["local"]).is_file(): raise FarmError(f"Expected executor output missing: {f['name']}")
    provenance["duration_seconds"]=round(time.monotonic()-started,3)
    return {"files":files,"metrics":metrics,"mock":bool((task.get('parent_output') or {}).get('mock')),"provenance":provenance}
