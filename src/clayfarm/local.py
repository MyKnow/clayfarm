"""SQLite reference coordinator for deterministic tests / local demo.
Not a LAN server, not a substitute for a durable remote Supabase deployment.
"""
from __future__ import annotations
import json
import contextlib
import shutil
import sqlite3
import time
from pathlib import Path
from .util import FarmError, canonical, new_id, safe_key, digest, native_path, sqlite_path


class LocalBackend:
    def __init__(self, root: Path, user_id="local-worker", role="worker", clock=time.time):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.user_id=user_id; self.role=role; self.clock=clock
        self.farm_id="00000000-0000-0000-0000-000000000001"
        with self.connect() as db:
            db.execute("pragma journal_mode=WAL")
            db.execute("create table if not exists jobs (id text primary key,data text not null)")
            db.execute("create table if not exists tasks (id text primary key,data text not null)")
            db.execute("create table if not exists workers (id text primary key,data text not null)")

    @contextlib.contextmanager
    def connect(self):
        db=sqlite3.connect(sqlite_path(self.root/"queue.sqlite"),timeout=20)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _put(self,db,table,record):
        db.execute(f"insert into {table} values (?,?) on conflict(id) do update set data=excluded.data",(record["id"],canonical(record)))

    def rpc(self, action, args=None):
        args=args or {}; now=self.clock()
        with self.connect() as db:
            db.execute("begin immediate")
            jobs={r[0]:json.loads(r[1]) for r in db.execute("select * from jobs")}
            tasks={r[0]:json.loads(r[1]) for r in db.execute("select * from tasks")}
            if action=="me": return {"user_id":self.user_id,"farm_id":self.farm_id,"role":self.role}
            if action=="heartbeat":
                self._put(db,"workers",{"id":self.user_id,**args,"last_seen":now})
                return {"ok":True}
            if action=="workers": return [json.loads(r[1]) for r in db.execute("select * from workers")]
            if action=="submit":
                if self.role!="caller": raise FarmError("caller_only")
                if args["id"] in jobs:
                    old=jobs[args["id"]]
                    if old["request_hash"]!=args["request_hash"] or old["created_by"]!=self.user_id: raise FarmError("idempotency_conflict")
                    return {"id":old["id"],"existing":True}
                job={k:v for k,v in args.items() if k!="tasks"}
                job.update(farm_id=self.farm_id,created_by=self.user_id,status="open",created_at=now)
                self._put(db,"jobs",job)
                seen=set()
                for raw in args["tasks"]:
                    t=dict(raw)
                    if t["parent_id"] and t["parent_id"] not in seen: raise FarmError("parent_must_precede_child")
                    if t["job_id"]!=job["id"] or t["id"] in tasks or t["id"] in seen: raise FarmError("invalid_task")
                    seen.add(t["id"])
                    t.update(status="queued",compute_done=False,attempt_no=0,max_attempts=3,attempt_id=None,lease_owner=None,lease_until=None,not_before=now,created_at=now,output=None)
                    self._put(db,"tasks",t)
                return {"id":job["id"],"existing":False}
            if action in ("get","approve","cancel"):
                job=jobs.get(args["id"])
                if not job: raise FarmError("job_not_found")
                if action in ("approve","cancel") and (self.role!="caller" or job["created_by"]!=self.user_id): raise FarmError("originating_caller_only")
                if action=="get": return {"job":job,"tasks":[t for t in tasks.values() if t["job_id"]==job["id"]]}
                if action=="approve":
                    t=tasks.get(args["task_id"],{})
                    if job["status"]!="open" or t.get("job_id")!=job["id"] or t.get("status")!="done" or t.get("kind")!="process": raise FarmError("completed_process_required")
                    if t["output"].get("mock"): raise FarmError("mock_assets_cannot_be_approved")
                    if not t["output"].get("metrics",{}).get("hard_pass"): raise FarmError("mechanical_checks_failed")
                    if any(c["parent_id"]==t["id"] and c["status"]!="done" for c in tasks.values()): raise FarmError("preview_incomplete")
                    job["status"]="approved"; job["approved_task"]=t["id"]
                else: job["status"]="cancelled"
                self._put(db,"jobs",job)
                for t in tasks.values():
                    if t["job_id"]==job["id"] and t["status"] in ("queued","running"):
                        t["status"]="cancelled"; t["lease_until"]=None; self._put(db,"tasks",t)
                return {job["status"]:True}
            if self.role!="worker": raise FarmError("worker_only")
            if action in ("claim","peek"):
                for t in tasks.values():
                    if t["status"]=="running" and t["lease_until"]<=now and t["attempt_no"]>=t["max_attempts"]:
                        t["status"]="failed"; t["error"]={"code":"attempts_exhausted"}; self._put(db,"tasks",t)
                changed=True
                while changed:
                    changed=False
                    for t in tasks.values():
                        if t["status"] in ("queued","running") and t["parent_id"] and tasks[t["parent_id"]]["status"] in ("failed","cancelled"):
                            t["status"]="failed"; t["error"]={"code":"dependency_failed"}; self._put(db,"tasks",t); changed=True
                row=db.execute("select data from workers where id=?",(self.user_id,)).fetchone()
                caps=json.loads(row[0])["capabilities"] if row else []
                available=[t for t in tasks.values() if t["slot"]==args["slot"] and t["capability"] in caps and jobs[t["job_id"]]["status"]=="open"
                           and (t["status"]=="queued" or (action=="claim" and t["status"]=="running" and t["lease_until"]<=now))
                           and t["attempt_no"]<t["max_attempts"] and t["not_before"]<=now
                           and (not t["parent_id"] or tasks[t["parent_id"]]["status"]=="done")
                           and (not args.get("task_id") or args["task_id"]==t["id"])]
                available.sort(key=lambda t:(-t["priority"],t["created_at"],t["id"]))
                def enriched(t): return {**t,"parent_output":tasks[t["parent_id"]]["output"] if t["parent_id"] else None}
                if action=="peek": return [enriched(t) for t in available[:2]]
                if any(t["lease_owner"]==self.user_id and t["status"]=="running" and t["slot"]==args["slot"] and not t.get("compute_done",False) and t["lease_until"]>now for t in tasks.values()): return None
                if not available: return None
                t=available[0]; t.update(status="running",compute_done=False,lease_owner=self.user_id,lease_until=now+args.get("seconds",120),attempt_id=new_id(),attempt_no=t["attempt_no"]+1)
                self._put(db,"tasks",t)
                return enriched(t)
            if action in ("renew","computed","finish","fail"):
                t=tasks.get(args["task_id"])
                if not t: raise FarmError("task_not_found")
                same=t["attempt_id"]==args["attempt_id"] and t["lease_owner"]==self.user_id
                if action=="finish" and same and t["status"]=="done": return {"accepted":True,"already_committed":True}
                if not same or t["status"]!="running" or (t["lease_until"] or 0)<=now or jobs[t["job_id"]]["status"]!="open": return {"accepted":False,"reason":"lease_lost"}
                if action=="computed": t["compute_done"]=True
                elif action=="renew": t["lease_until"]=now+args.get("seconds",120)
                elif action=="finish":
                    for f in args["output"]["files"]:
                        key=safe_key(f["path"])
                        if not key.startswith(f"{self.farm_id}/{self.user_id}/{t['id']}/{t['attempt_id']}/"): raise FarmError("invalid_artifact_scope")
                        if not native_path(self.root/"objects"/key).exists(): raise FarmError("upload_before_commit")
                    t.update(status="done",lease_until=None,output=args["output"],completed_at=now)
                else:
                    t.update(status="failed" if t["attempt_no"]>=t["max_attempts"] else "queued",lease_until=None,error=args["error"],not_before=now)
                self._put(db,"tasks",t)
                return {"accepted":True}
            raise FarmError("unknown_action")

    def upload(self, path: Path, key: str, state_dir: Path):
        dest=native_path(self.root/"objects"/safe_key(key)); dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if digest(dest)!=digest(path): raise FarmError("immutable_artifact_conflict")
        else:
            tmp=dest.with_name(dest.name+"."+new_id()+".partial")
            shutil.copyfile(path,tmp); tmp.replace(dest)

    def download(self, blob: dict, dest: Path):
        src=native_path(self.root/"objects"/safe_key(blob["path"]))
        if not src.is_file(): raise FarmError("missing_artifact")
        dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(src,dest)
        if digest(dest)!=blob["sha256"]: dest.unlink(); raise FarmError("artifact_hash_mismatch")
