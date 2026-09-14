from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.resources
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from . import __version__
from .local import LocalBackend
from .png import contact_sheet, encode
from .remote import SupabaseBackend
from .setup import admin_init, doctor, enroll, load_config, warm
from .spec import validate_spec, plan, VIEWS
from .util import FarmError, OfflineError, ProcessLock, atomic_bytes, canonical, check_uuid, digest, home_dir, new_id, read_json, safe_file, write_json
from .worker import Worker


def backend(cfg):
    if cfg.get("backend")=="local": return LocalBackend(Path(cfg["local_root"]),cfg["user_id"],cfg.get("role","worker"))
    return SupabaseBackend(cfg)


def upload_input(client,path,job,home):
    path=Path(path).resolve()
    if not path.is_file(): raise FarmError(f"Input does not exist: {path}")
    if path.suffix.lower() not in (".png",".jpg",".jpeg",".glb"): raise FarmError("Inputs must be PNG, JPEG or GLB")
    name="concept"+path.suffix.lower(); sha=digest(path)
    key=f"{client.farm_id}/{client.user_id}/{job}/inputs/{sha}-{name}"
    client.upload(path,key,home/"uploads")
    return {"path":key,"name":name,"sha256":sha,"size":path.stat().st_size,"role":"input"}


def submit_job(client,home,spec,concepts,engines,caller,job_id=None,parent=None,raw_mesh=None):
    spec=validate_spec(spec); jid=check_uuid(job_id) if job_id else new_id()
    paths=[Path(p).resolve() for p in concepts]
    # Intent is durable before the first network operation. --retry-submit reuses this exact ID/plan.
    intent={"id":jid,"spec":spec,"concepts":[str(p) for p in paths],"engines":engines,"caller":caller,"parent":parent,"raw_mesh":raw_mesh}
    spool=home/"submissions"/jid; spool.mkdir(parents=True,exist_ok=True)
    existing=read_json(spool/"intent.json")
    if existing and existing!=intent: raise FarmError("Job ID already has a different local submission intent")
    write_json(spool/"intent.json",intent)
    request=read_json(spool/"request.json")
    if request is None:
        blobs=[upload_input(client,path,jid,home) for path in paths]
        tasks=plan(jid,spec,blobs,engines,raw_mesh=raw_mesh)
        request={"id":jid,"spec":spec,"tasks":tasks,"caller":caller,"parent_job":parent}
        request["request_hash"]=hashlib.sha256(canonical(request).encode()).hexdigest()
        write_json(spool/"request.json",request)
    reply=client.rpc("submit",request)
    return {"job_id":reply["id"],"candidates":len({t['payload']['candidate'] for t in request['tasks']}),"tasks":len(request["tasks"]),
            "status":"submitted","caller":caller,"retry_file":str(spool/"intent.json")}


def retry_submit(client,home,jid):
    spool=home/"submissions"/check_uuid(jid)
    request=read_json(spool/"request.json")
    if request: return client.rpc("submit",request)
    intent=read_json(spool/"intent.json")
    if not intent: raise FarmError("No locally saved submission intent for this job")
    return submit_job(client,home,intent["spec"],intent["concepts"],intent["engines"],intent["caller"],jid,intent["parent"],intent["raw_mesh"])


def review_ready(view):
    tasks=view["tasks"]
    return [t for t in tasks if t["kind"]=="process" and t["status"]=="done"
            and all(c["status"]=="done" for c in tasks if c["parent_id"]==t["id"])]


def collect_result(client,jid,out,*,wait=0,all_candidates=False,artifacts=False):
    check_uuid(jid); deadline=time.monotonic()+wait
    while True:
        view=client.rpc("get",{"id":jid})
        terminal=all(t["status"] in ("done","failed","cancelled") for t in view["tasks"])
        if time.monotonic()>=deadline or terminal or (review_ready(view) and not all_candidates): break
        time.sleep(min(5,max(0,deadline-time.monotonic())))
    out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True)
    spec=view["job"]["spec"]; rows=[]; candidates=[]; diagnostics=[]
    by_id={t['id']:t for t in view['tasks']}
    def mock_ancestry(task):
        seen=set()
        while task:
            if task['id'] in seen: return True  # Invalid lineage cannot be ready.
            seen.add(task['id'])
            if task.get('capability')=='mock' or (task.get('output') or {}).get('mock'): return True
            task=by_id.get(task.get('parent_id'))
        return False
    for task in sorted(review_ready(view),key=lambda t:t["payload"]["candidate"]):
        candidate=task["payload"]["candidate"]; safe_file(candidate)
        previews={c["payload"]["view"]:c for c in view["tasks"] if c["parent_id"]==task["id"] and c["kind"]=="preview" and c["status"]=="done"}
        images=[]
        for direction in spec["views"]:
            for blob in previews[direction]["output"]["files"]:
                if blob["role"]=="preview":
                    target=out/candidate/(direction+".png"); client.download(blob,target); images.append(target)
        row={"candidate":candidate,"process_task":task["id"],"metrics":task["output"].get("metrics",{}),"mock":mock_ancestry(task),"previews":[str(p) for p in images]}
        if artifacts:
            row["artifacts"]=[]
            for blob in task["output"]["files"]:
                path=out/candidate/safe_file(blob["name"]); client.download(blob,path); row["artifacts"].append(str(path))
        rows.append(images)
        if not row['mock'] and row['metrics'].get('hard_pass') is True:
            candidates.append(row)
        else:
            row['diagnostic_reason']='synthetic_ancestry' if row['mock'] else 'mechanical_checks_not_passed'
            diagnostics.append(row)
    result={"job_id":jid,"name":spec["name"],"caller":view["job"].get("caller",{}),"job_status":view["job"]["status"],
            "status":"review_ready" if candidates else "diagnostic_only" if diagnostics else "no_usable_candidate" if terminal else "pending", "all_terminal":terminal,
            "ready_candidates":candidates,"diagnostic_candidates":diagnostics,"columns":spec["views"],"pending_tasks":sum(t["status"] in ("queued","running") for t in view["tasks"]),
            "failures":[{"task":t["id"],"kind":t["kind"],"error":t.get("error",{})} for t in view["tasks"] if t["status"]=="failed"][:8],
            "approved_task":view["job"].get("approved_task"),"note":"Mechanical pass is not aesthetic approval. Same caller must inspect the previews before approve."}
    if rows:
        contact_sheet(rows,out/"contact-sheet.png",labels=[spec["views"] for _ in rows])
        result["contact_sheet"]=str(out/"contact-sheet.png")
    write_json(out/"report.json",result)
    result["report"]=str(out/"report.json")
    return result


def demo(out: Path):
    out=out.resolve(); out.mkdir(parents=True,exist_ok=True)
    root=out/"coordinator"; home=out/"caller"
    client=LocalBackend(root,"local-caller","caller")
    n=64; concept=out/"fixture-input.png"
    atomic_bytes(concept,encode(n,n,bytes([230,210,190,255])*(n*n)))
    reply=submit_job(client,home,{"name":"MOCK-fixture","views":list(VIEWS)},[concept],["mock"],{"agent":"demo","session":"synthetic-fixture"})
    configs=[]; workers=[]
    for i in range(5):
        cfg={"home":str(out/f"node-{i}"),"allow_mock":True,"allow_battery":True,"mock_delay":0.01,"min_disk_free_mb":0,"gpu_min_ram_mb":0,"cpu_min_ram_mb":0}
        worker=Worker(cfg,LocalBackend(root,f"local-worker-{i}")); worker.refresh(); workers.append(worker); configs.append(cfg)
    stop=threading.Event(); errors=[]
    def loop(worker):
        try:
            for _ in range(100):
                if stop.is_set(): return
                did=worker.step("gpu") or worker.step("cpu")
                worker.flush()
                if not did: time.sleep(.01)
        except Exception as e: errors.append(str(e)); stop.set()
    threads=[threading.Thread(target=loop,args=(w,)) for w in workers]
    for t in threads:t.start()
    for t in threads:t.join()
    if errors: raise FarmError("Demo failed: "+str(errors))
    result=collect_result(client,reply["job_id"],out/"review",artifacts=True)
    if not result["all_terminal"] or not result["diagnostic_candidates"]: raise FarmError("Demo did not finish")
    result["demo_warning"]="Synthetic MOCK executor. Proves queue/DAG/transfer/review plumbing, NOT GPU inference or asset quality. Approval is intentionally blocked."
    write_json(out/"demo-result.json",result)
    return result


def selftest_blender(cfg):
    from .executors import execute, mock_glb
    from .resources import blender_signature
    cfg.pop("blender_selftest",None)
    write_json(Path(cfg["home"])/"config.json",cfg,secret=True)
    folder=Path(cfg["home"])/"blender-smoke"
    folder.mkdir(parents=True,exist_ok=True)
    atomic_bytes(folder/"fixture.glb",mock_glb())
    spec=validate_spec({"name":"blender_smoke","target_triangles":100,"preview_size":128,
                        "geometry":{"remesh":"voxel","smooth_iterations":1},
                        "material":{"preset":"cream"},"lod_ratios":[.5,.25],"collider":"convex_hull"})
    task={"kind":"process","capability":"blender","payload":{"spec":spec}}
    result=execute(task,folder/"fixture.glb",folder/"process",cfg,threading.Event())
    if not result["metrics"].get("hard_pass"): raise FarmError("Blender selftest mechanical checks failed")
    from .png import decode
    images=[]
    for view in spec["views"]:
        task={"kind":"preview","capability":"blender","payload":{"spec":spec,"view":view}}
        execute(task,folder/"process"/"mesh.glb",folder/view,cfg,threading.Event())
        path=folder/view/"preview.png"; width,height,pixels=decode(path.read_bytes())
        if width!=128 or height!=128 or not any(pixels[3::4]): raise FarmError("Empty or invalid preview")
        images.append(path)
    contact_sheet([images[:3],images[3:]],folder/"contact-sheet.png",128,labels=[spec["views"][:3],spec["views"][3:]])
    receipt={"blender_smoke_pass":True,"metrics":result["metrics"],"preview":str(folder/"contact-sheet.png"),
             "views":spec["views"],"signature":blender_signature(cfg),"note":"Procedural test fixture, not AI output"}
    cfg["blender_selftest"]={"signature":receipt["signature"],"tested_at":time.time()}
    write_json(Path(cfg["home"])/"config.json",cfg,secret=True)
    write_json(folder/"receipt.json",receipt)
    return receipt


def parser():
    p=argparse.ArgumentParser(prog="assetgen / assetnode",description="ClayFarm: cloud caller directs; local workers implement; cloud caller reviews")
    p.add_argument("--version",action="version",version=__version__)
    p.add_argument("--home",type=Path,default=None)
    sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("admin-init",help="Create isolated caller/node accounts (admin secret is never saved)")
    s.add_argument("--out",type=Path,default=Path("enrollments")); s.add_argument("--workers",type=int,default=4); s.add_argument("--apple",type=int,default=1)
    s=sub.add_parser("enroll"); s.add_argument("file",type=Path)
    s=sub.add_parser("doctor"); s.add_argument("--online",action="store_true")
    sub.add_parser("worker"); sub.add_parser("status"); sub.add_parser("pause"); sub.add_parser("resume"); sub.add_parser("stop"); sub.add_parser("install-check")
    s=sub.add_parser("configure"); s.add_argument("--blender"); s.add_argument("--cpu-threads",type=int)
    s.add_argument("--offline-speculation",action=argparse.BooleanOptionalAction,default=None); s.add_argument("--allow-battery",action=argparse.BooleanOptionalAction,default=None)
    s=sub.add_parser("warm"); s.add_argument("--engine",choices=["sf3d","triposr"],required=True); s.add_argument("--repo"); s.add_argument("--python"); s.add_argument("--test-image",required=True)
    s.add_argument("--install",action="store_true"); s.add_argument("--ref"); s.add_argument("--model-revision"); s.add_argument("--accept-model-license",action="store_true")
    s=sub.add_parser("selftest"); s.add_argument("--blender",help="Optional executable; selftest can run before enrollment")
    s=sub.add_parser("submit"); s.add_argument("--concept",action="append",required=True); s.add_argument("--spec",type=Path,required=True)
    s.add_argument("--engine",action="append",choices=["sf3d","triposr"],required=True); s.add_argument("--caller",choices=["codex","claude","human"],default="human")
    s.add_argument("--session",default=""); s.add_argument("--job-id"); s.add_argument("--parent-job")
    s=sub.add_parser("retry-submit"); s.add_argument("job_id")
    s=sub.add_parser("result"); s.add_argument("job_id"); s.add_argument("--out",type=Path); s.add_argument("--wait",type=int,default=0)
    s.add_argument("--all",action="store_true"); s.add_argument("--artifacts",action="store_true")
    s=sub.add_parser("revise"); s.add_argument("job_id"); s.add_argument("--task",required=True); s.add_argument("--patch",type=Path,required=True)
    s=sub.add_parser("approve"); s.add_argument("job_id"); s.add_argument("--task",required=True)
    s=sub.add_parser("cancel"); s.add_argument("job_id")
    sub.add_parser("nodes")
    s=sub.add_parser("demo"); s.add_argument("--out",type=Path,default=Path("clayfarm-demo"))
    s=sub.add_parser("skills"); s.add_argument("--project",type=Path,required=True); s.add_argument("--target",choices=["codex","claude","both"],default="both")
    s=sub.add_parser("update"); s.add_argument("bundle",type=Path); s.add_argument("--sha256",required=True)
    return p


def dispatch(args):
    home=(args.home or home_dir()).expanduser().resolve(); c=args.command
    if c=="admin-init": return admin_init(args.out,args.workers,args.apple)
    if c=="enroll": return enroll(args.file,home)
    if c=="demo": return demo(args.out)
    if c=="install-check":
        with ProcessLock(home/"worker.lock"): return {"safe_to_install":True}
    if c in ("pause","resume","stop"):
        home.mkdir(parents=True,exist_ok=True)
        if c=="pause": atomic_bytes(home/"PAUSED",b"user paused new claims\n")
        elif c=="resume": (home/"PAUSED").unlink(missing_ok=True)
        else: atomic_bytes(home/"STOP",b"drain and exit\n")
        return {"action":c,"note":"Running tasks drain; pause/resume does not terminate work. After stop, start with assetnode worker or the OS autostart task."}
    if c=="skills":
        shared=next((parent/".agents/skills/clayfarm/SKILL.md" for parent in Path(__file__).resolve().parents
                     if (parent/".agents/skills/clayfarm/SKILL.md").is_file()),None)
        content=shared.read_bytes() if shared else importlib.resources.files("clayfarm").joinpath("skill.md").read_bytes()
        paths=[]
        path=args.project.resolve()/".agents/skills/clayfarm/SKILL.md"
        if path.exists() and path.read_bytes()!=content: raise FarmError(f"Existing skill differs; refusing to overwrite {path}")
        atomic_bytes(path,content); paths.append(str(path))
        return {"installed":paths,"note":"This skill wraps the CLI. It does not create image-generation privileges or resume a terminated agent session."}
    if c=="update":
        if digest(args.bundle)!=args.sha256.lower(): raise FarmError("Release checksum mismatch")
        dest=home/"bin"/"clayfarm.pyz"
        with ProcessLock(home/"worker.lock"):
            if not dest.exists(): raise FarmError("Use install.sh/install.ps1 for first installation")
            subprocess.run([sys.executable,str(args.bundle.resolve()),"--version"],check=True,capture_output=True,timeout=15)
            shutil.copyfile(dest,dest.with_suffix(".previous.pyz"))
            atomic_bytes(dest,args.bundle.read_bytes())
        return {"updated":str(dest),"rollback":str(dest.with_suffix('.previous.pyz'))}
    if c=="selftest":
        cfg=read_json(home/"config.json",{"home":str(home)})
        cfg["home"]=str(home)
        if args.blender: cfg["blender"]=str(Path(args.blender).resolve())
        with ProcessLock(home/"worker.lock"): return selftest_blender(cfg)
    cfg=load_config(home)
    if c=="configure":
        if args.cpu_threads is not None and not 1<=args.cpu_threads<=16: raise FarmError("cpu-threads must be in [1,16]")
        for key in ("blender","cpu_threads","offline_speculation","allow_battery"):
            value=getattr(args,key)
            if value is not None: cfg[key]=value
        write_json(home/"config.json",cfg,secret=True)
        return {"configured":True,"note":"Restart/drain the worker to apply configuration changes"}
    if c=="doctor": return doctor(cfg,args.online)
    if c=="warm":
        with ProcessLock(home/"worker.lock"):
            return warm(cfg,args.engine,args.repo,args.python,args.test_image,args.install,args.ref,args.model_revision,args.accept_model_license)
    if c=="selftest":
        with ProcessLock(home/"worker.lock"): return selftest_blender(cfg)
    client=backend(cfg)
    if c=="worker":
        if cfg.get("role")!="worker": raise FarmError("Use a worker enrollment; caller credentials never claim tasks")
        Worker(cfg,client).run_forever(); return {"stopped":True}
    if c=="status":
        from .journal import Journal
        journal=Journal(home/"worker.sqlite")
        return {"name":cfg["name"],"status":journal.get("status",{}),"last_error":journal.get("last_error"),
                "pending_uploads":len(journal.entries(["pending","failure_pending"])),"paused":(home/"PAUSED").exists()}
    if c=="submit":
        return submit_job(client,home,read_json(args.spec),args.concept,args.engine,{"agent":args.caller,"session":args.session},args.job_id,args.parent_job)
    if c=="retry-submit": return retry_submit(client,home,args.job_id)
    if c=="result":
        if not 0<=args.wait<=3600: raise FarmError("wait must be in [0,3600] seconds")
        return collect_result(client,args.job_id,args.out or home/"reviews"/check_uuid(args.job_id),wait=args.wait,all_candidates=args.all,artifacts=args.artifacts)
    if c=="revise":
        view=client.rpc("get",{"id":check_uuid(args.job_id)})
        selected=next((t for t in view["tasks"] if t["id"]==check_uuid(args.task) and t["kind"]=="process" and t["status"]=="done"),None)
        if not selected: raise FarmError("Choose a completed process task")
        if selected["output"].get("mock"): raise FarmError("Cannot promote a mock fixture through revision")
        patch=read_json(args.patch)
        if not isinstance(patch,dict): raise FarmError("Patch must be a JSON object containing supported spec fields")
        spec=validate_spec({**view["job"]["spec"],**patch})
        parent=next((t for t in view["tasks"] if t["id"]==selected["parent_id"]),None)
        raw=next((f for f in parent["output"]["files"] if f["role"]=="mesh"),None) if parent else selected["payload"].get("input")
        if not raw: raise FarmError("Original mesh unavailable; resubmit with a new concept")
        return submit_job(client,home,spec,[],["sf3d"],view["job"].get("caller",{}),parent=args.job_id,raw_mesh=raw)
    if c=="approve": return client.rpc("approve",{"id":check_uuid(args.job_id),"task_id":check_uuid(args.task)})
    if c=="cancel": return client.rpc("cancel",{"id":check_uuid(args.job_id)})
    if c=="nodes": return client.rpc("workers")
    raise FarmError("Unknown command")


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result=dispatch(args)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"error":"interrupted","note":"Local state retained"}),file=sys.stderr); return 130
    except (FarmError,OSError,ValueError,subprocess.SubprocessError) as e:
        print(json.dumps({"error":type(e).__name__,"message":str(e)},ensure_ascii=False),file=sys.stderr)
        if args.command=="submit":
            home=(args.home or home_dir()).expanduser().resolve()
            pending=sorted((home/"submissions").glob("*/intent.json"),key=lambda p:p.stat().st_mtime,reverse=True)
            if pending: print(json.dumps({"retry_job_id":pending[0].parent.name,"command":"assetgen retry-submit "+pending[0].parent.name}),file=sys.stderr)
        return 75 if isinstance(e,OfflineError) else 1


if __name__=="__main__": raise SystemExit(main())
