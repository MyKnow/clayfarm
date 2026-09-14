from __future__ import annotations
import getpass
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from .remote import request, base_url, SupabaseBackend, ApiError
from .resources import blender_path, blender_ready, gpu_stats, probe, telemetry, capabilities
from .util import FarmError, check_uuid, new_id, read_json, write_json, ProcessLock


def load_config(home):
    cfg=read_json(home/"config.json")
    if not cfg: raise FarmError("Node is not enrolled. Run assetnode enroll <enrollment.json> first")
    cfg["home"]=str(home)
    return cfg


def enroll(path,home):
    record=read_json(path)
    required={"url","publishable_key","email","password","user_id","farm_id","role","name"}
    if not isinstance(record,dict) or not required<=record.keys(): raise FarmError("Invalid enrollment file")
    base_url(record["url"]); check_uuid(record["user_id"]); check_uuid(record["farm_id"])
    if record["role"] not in ("caller","worker"): raise FarmError("Invalid enrollment role")
    if set(record)-required-{"profile","storage_url"}: raise FarmError("Unexpected enrollment fields")
    SupabaseBackend(record)  # reject privileged credentials before persisting anything
    previous=read_json(home/"config.json",{})
    if previous and previous.get("user_id")!=record["user_id"]:
        raise FarmError("This home is already enrolled as another node; use a different --home")
    cfg={"lease_seconds":120,"cpu_threads":2,"prefetch":2,"offline_speculation":False,"allow_battery":False,
         "min_free_vram_mb":7000,"max_external_gpu_util":20,"engines":{},**previous,**record,"home":str(home)}
    home.mkdir(parents=True,exist_ok=True)
    if os.name!="nt": os.chmod(home,0o700)
    write_json(home/"config.json",cfg,secret=True)
    return {"enrolled":cfg["name"],"role":cfg["role"],"profile":cfg.get("profile","auto"),"config":str(home/"config.json"),"note":"Enrollment is stored; doctor --online verifies remote access. Delete the transferred enrollment copy."}


def admin_init(out: Path, workers: int, apple: int):
    if not 0<=workers<=20 or not 0<=apple<=20: raise FarmError("Invalid node count")
    if out.exists() and any(out.iterdir()): raise FarmError("Enrollment output directory must be empty to prevent credential overwrite")
    url=base_url(input("Supabase HTTPS project URL: ").strip())
    key=input("Publishable (or legacy anon) key: ").strip()
    secret=getpass.getpass("Supabase secret / service_role key (admin only; not stored): ").strip()
    if not secret: raise FarmError("Admin credential is required")
    headers={"apikey":secret}
    if secret.count(".")==2: headers["Authorization"]="Bearer "+secret
    # Verify schema is present before creating identities.
    request(url+"/rest/v1/cf_members?select=user_id&limit=1",headers=headers)
    try:
        request(url+"/storage/v1/bucket/clayfarm",headers=headers)
    except ApiError as e:
        if e.status not in (400,404): raise
        request(url+"/storage/v1/bucket","POST",{"id":"clayfarm","name":"clayfarm","public":False,"file_size_limit":50*1024*1024},headers)
    out.mkdir(parents=True,exist_ok=True)
    if os.name!="nt": os.chmod(out,0o700)
    farm=new_id(); made=[]
    for name,role,profile in [("caller","caller","auto")]+[(f"gpu-{i+1:02}","worker","cuda") for i in range(workers)]+[(f"mac-{i+1:02}","worker","apple") for i in range(apple)]:
        email=f"clayfarm-{new_id()}@nodes.invalid"; password=secrets.token_urlsafe(36)
        _,_,body=request(url+"/auth/v1/admin/users","POST",{"email":email,"password":password,"email_confirm":True},headers)
        user=json.loads(body); uid=user.get("id") or user.get("user",{}).get("id")
        check_uuid(uid)
        # Save first: interrupted provisioning never leaves an unrecoverable identity.
        enrollment={"url":url,"publishable_key":key,"email":email,"password":password,"user_id":uid,"farm_id":farm,"role":role,"name":name,"profile":profile}
        write_json(out/f"{name}.enrollment.json",enrollment,secret=True)
        request(url+"/rest/v1/cf_members","POST",{"user_id":uid,"farm_id":farm,"role":role,"name":name},headers)
        made.append({"name":name,"file":str(out/f"{name}.enrollment.json")})
    write_json(out/"manifest.json",{"farm_id":farm,"created":made,"warning":"Do not commit or upload this folder. Each node receives ONLY its own enrollment file."},secret=True)
    return {"farm_id":farm,"enrollments":made}


def doctor(cfg,online=False):
    checks=[]
    checks.append({"check":"python","ok":sys.version_info>=(3,11),"detail":sys.version.split()[0]})
    checks.append({"check":"blender","ok":bool(blender_path(cfg)),"detail":blender_path(cfg) or "Install Blender 4.x or configure --blender <path>"})
    checks.append({"check":"blender_selftest","ok":blender_ready(cfg),"detail":"passed for current adapter and executable" if blender_ready(cfg) else "Run selftest; Blender work is disabled until it passes"})
    gpu=gpu_stats()
    checks.append({"check":"cuda","ok":bool(gpu),"detail":gpu or "No NVIDIA GPU; CPU Blender / Mac support worker only"})
    for name in ("sf3d","triposr"):
        e=cfg.get("engines",{}).get(name,{})
        checks.append({"check":name,"ok":bool(e.get("ready")),"detail":"smoke-tested" if e.get("ready") else "warm --engine ... --test-image ... required"})
    if online:
        try:
            member=SupabaseBackend(cfg).rpc("me")
            checks.append({"check":"supabase_membership","ok":member["user_id"]==cfg["user_id"],"detail":member["role"]})
        except FarmError as e: checks.append({"check":"supabase_membership","ok":False,"detail":str(e)})
    return {"checks":checks,"telemetry":telemetry(cfg),"capabilities":capabilities(cfg),"note":"Not a performance benchmark. Missing CUDA is normal on a Mac; missing real executors is not generation-ready."}


def warm(cfg,engine,repo,python,test_image,install=False,ref=None,model_revision=None,accept_license=False):
    """Use an existing engine env, or explicitly bootstrap an isolated CUDA env.
    GPU compilation and upstream weights are never bundled into the worker archive.
    """
    from .executors import run
    from .util import digest
    import threading
    if engine not in ("sf3d","triposr"): raise FarmError("Unknown engine")
    if not gpu_stats(): raise FarmError("v1 reconstruction requires an NVIDIA CUDA node. Mac is a Blender/CPU worker")
    if engine=="sf3d" and not accept_license: raise FarmError("Read the Stability AI Community license; pass --accept-model-license only after accepting its terms")
    if not test_image or not Path(test_image).is_file(): raise FarmError("A local --test-image is required to prove the executor actually runs")
    home=Path(cfg["home"]); base=home/"engines"/engine; base.mkdir(parents=True,exist_ok=True)
    log=base/"setup.log"; cancelled=threading.Event()
    urls={"sf3d":"https://github.com/Stability-AI/stable-fast-3d.git","triposr":"https://github.com/VAST-AI-Research/TripoSR.git"}
    models={"sf3d":"stabilityai/stable-fast-3d","triposr":"stabilityai/TripoSR"}
    # Do not keep advertising a previously ready engine while its environment is being modified.
    cfg.setdefault("engines",{}).setdefault(engine,{})["ready"]=False
    write_json(home/"config.json",cfg,secret=True)
    repo=Path(repo).expanduser().resolve() if repo else base/"repo"
    python=Path(python).expanduser().resolve() if python else base/("venv/Scripts/python.exe" if os.name=="nt" else "venv/bin/python")
    if install:
        if not shutil.which("git") or not shutil.which("uv"): raise FarmError("Automatic engine setup requires Git and uv. Worker-only installation does not")
        def setup_run(argv,label):
            print(json.dumps({"setup":engine,"step":label,"log":str(log)}),flush=True)
            run(argv,base,log,3600,cancelled)
        if not repo.exists(): setup_run(["git","clone","--no-checkout",urls[engine],str(repo)],"fetch_upstream")
        existing=cfg.get("engines",{}).get(engine,{})
        chosen=ref or existing.get("git_commit") or "origin/main"
        if ref: setup_run(["git","-C",str(repo),"fetch","origin",ref],"fetch_pinned_revision")
        setup_run(["git","-C",str(repo),"checkout","--detach",chosen],"pin_worktree")
        if not python.is_file(): setup_run(["uv","venv","--python","3.11",str(base/"venv")],"create_isolated_environment")
        setup_run(["uv","pip","install","--python",str(python),"torch==2.5.1","torchvision==0.20.1","--index-url","https://download.pytorch.org/whl/cu124"],"install_pytorch_cuda124")
        setup_run(["uv","pip","install","--python",str(python),"setuptools==69.5.1","wheel==0.45.1","pip==25.0.1"],"prepare_build_tools")
        setup_run(["uv","pip","install","--python",str(python),"--no-build-isolation","-r",str(repo/"requirements.txt")],"install_upstream_dependencies")
    if not (repo/"run.py").is_file() or not python.is_file():
        raise FarmError("Engine environment missing. Use --install or provide --repo and --python for an existing installation")
    commit=probe(["git","-C",str(repo),"rev-parse","HEAD"])
    if not commit: raise FarmError("Engine repo must be a Git checkout so its revision can be audited")
    run([str(python),"-c","import torch; assert torch.cuda.is_available(), 'CUDA unavailable'"],repo,log,120,cancelled)
    # Resolve once, then pass an absolute snapshot path on every generation. No floating model head.
    revision=model_revision or cfg.get("engines",{}).get(engine,{}).get("model_revision") or "main"
    resolver=base/"resolve_model.py"
    resolver.write_text("import json,sys\nfrom huggingface_hub import snapshot_download\np=snapshot_download(repo_id=sys.argv[1],revision=sys.argv[2])\nopen(sys.argv[3],'w').write(json.dumps({'path':p}))\n",encoding="utf-8")
    run([str(python),str(resolver),models[engine],revision,str(base/"model.json")],repo,log,3600,cancelled)
    model_path=Path(read_json(base/"model.json")["path"])
    out=base/('smoke-'+secrets.token_hex(6)); out.mkdir()
    online=out/'online';offline=out/'offline'
    argv=[str(python),str(repo/"run.py"),str(Path(test_image).resolve()),"--output-dir",str(out)]
    if engine=="sf3d": argv += ["--device","cuda","--pretrained-model",str(model_path),"--texture-resolution","1024","--remesh_option","none"]
    else: argv += ["--device","cuda:0","--pretrained-model-name-or-path",str(model_path),"--model-save-format","glb","--chunk-size","4096"]
    # First smoke run also warms rembg. A second run verifies model downloads are not required.
    position=argv.index('--output-dir')+1
    argv[position]=str(online)
    run(argv,repo,base/"smoke-online.log",3600,cancelled)
    argv[position]=str(offline)
    run(argv,repo,base/"smoke-offline.log",3600,cancelled,{"HF_HUB_OFFLINE":"1"})
    for generated in (online,offline):
        mesh=generated/'0'/'mesh.glb'
        if not mesh.is_file() or mesh.read_bytes()[:4]!=b'glTF': raise FarmError('Smoke test did not produce a fresh GLB')
    if engine=='triposr':
        from .mesh_coordinates import triposr_to_gltf
        from .util import atomic_bytes
        for generated in (online,offline):
            mesh=generated/'0'/'mesh.glb'
            atomic_bytes(mesh,triposr_to_gltf(mesh.read_bytes()))
    mesh=offline/'0'/'mesh.glb'
    write_json(base/'latest-smoke.json',{'artifact':str(mesh),'online':str(online/'0'/'mesh.glb')})
    record={"repo":str(repo),"python":str(python),"git_commit":commit,"model_dir":str(model_path),"model_revision":model_path.name,
            "ready":True,"offline_ready":True,"smoke_sha256":digest(mesh)}
    cfg.setdefault("engines",{})[engine]=record
    write_json(home/"config.json",cfg,secret=True)
    with (base/"environment.freeze.txt").open("w",encoding="utf-8") as f:
        subprocess.run([str(python),"-m","pip","freeze"],stdout=f,check=False)
    write_json(base/"resolved-recipe.json",{k:v for k,v in record.items() if k not in ("repo","python","model_dir")})
    return {"ready":engine,"git_commit":commit,"model_revision":model_path.name,"note":"Per-node smoke test passed; visual suitability still requires caller review. Use these revisions on the other GPU nodes."}
