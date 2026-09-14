from __future__ import annotations
import contextlib
import hashlib
import os
import random
import re
import shutil
import threading
import time
from pathlib import Path
from .executors import execute
from .journal import Journal
from .resources import capabilities, can_run, telemetry
from .spec import task_fingerprint
from .util import FarmError, OfflineError, ProcessLock, digest, new_id, read_json, safe_file, write_json, native_path


class LeaseGuard:
    def __init__(self, backend, task, seconds, cancel):
        self.backend=backend; self.task=task; self.seconds=seconds; self.cancel=cancel
        self.stop=threading.Event(); self.thread=None

    def __enter__(self):
        def renew():
            while not self.stop.wait(max(1,self.seconds/3)):
                try:
                    reply=self.backend.rpc("renew",{"task_id":self.task["id"],"attempt_id":self.task["attempt_id"],"seconds":self.seconds})
                    if not reply.get("accepted"):
                        self.cancel.set(); return
                except OfflineError:
                    # A partition is not proof of process death. Finish bounded local work;
                    # only an authoritative, fenced commit can publish it later.
                    continue
                except FarmError:
                    self.cancel.set(); return
        if self.task.get("attempt_id"):
            self.thread=threading.Thread(target=renew,daemon=True); self.thread.start()
        return self

    def __exit__(self,*args):
        self.stop.set()
        if self.thread: self.thread.join(timeout=1)


class Worker:
    def __init__(self,cfg,backend):
        self.cfg=cfg; self.backend=backend; self.home=native_path(Path(cfg["home"]))
        self.home.mkdir(parents=True,exist_ok=True)
        self.journal=Journal(self.home/"worker.sqlite")
        self.shutdown=threading.Event(); self.sync_lock=threading.Lock(); self.upload_event=threading.Event(); self.cache_lock=threading.RLock()
        self.stats={}; self.caps=[]; self.seconds=int(cfg.get("lease_seconds",120))
        if not 15<=self.seconds<=600: raise FarmError("lease_seconds must be between 15 and 600")
        self.task_locks={}; self.task_locks_guard=threading.Lock()
        self.recover()

    def task_lock(self, task_id):
        with self.task_locks_guard:
            return self.task_locks.setdefault(task_id,threading.RLock())

    def recover(self):
        for row in self.journal.entries(["running"]):
            task=row["task"]
            marker=self.home/"work"/task["id"]/str(task.get("attempt_id") or "offline")/"result.json"
            result=read_json(marker)
            self.journal.save(task,"pending" if result else "cached",result)

    def refresh(self):
        self.stats=telemetry(self.cfg); self.caps=capabilities(self.cfg)
        self.journal.put("status",{**self.stats,"capabilities":self.caps,"pid":os.getpid(),"updated":time.time()})
        self.backend.rpc("heartbeat",{"capabilities":self.caps,"telemetry":self.stats})

    def input_blob(self,task):
        if task["payload"].get("input"): return task["payload"]["input"]
        for f in (task.get("parent_output") or {}).get("files",[]):
            if f["role"]=="mesh": return f
        raise FarmError("Task has no committed parent mesh")

    def input_path(self,task):
        blob=self.input_blob(task)
        sha=blob.get("sha256","")
        if not re.fullmatch("[0-9a-f]{64}",sha): raise FarmError("Invalid artifact SHA-256")
        name=safe_file(blob.get("name","input.glb"))
        return self.home/"cache"/(sha+Path(name).suffix.lower())

    def cache(self,task):
        with self.cache_lock:
            return self._cache(task)

    def _cache(self,task):
        path=self.input_path(task)
        if path.exists() and digest(path)==self.input_blob(task)["sha256"]: return path
        if shutil.disk_usage(self.home).free<int(self.cfg.get("min_disk_free_mb",1024))*1024*1024: raise FarmError("Not enough free disk for an asset task")
        self.backend.download(self.input_blob(task),path)
        return path

    def prefetch(self,slot):
        if int(self.cfg.get("prefetch",2))==0: return
        for task in (self.backend.rpc("peek",{"slot":slot}) or [])[:int(self.cfg.get("prefetch",2))]:
            if self.journal.state(task["id"]) not in (None,"cached"): continue
            self.cache(task)
            self.journal.cache_if_safe(task)

    def flush_one(self,row):
        task=row["task"]; result=row["result"]
        if row["state"]=="failure_pending":
            self.backend.rpc("fail",{"task_id":task["id"],"attempt_id":task["attempt_id"],"error":result})
            self.journal.save(task,"failed",result); return
        view=self.backend.rpc("get",{"id":task["job_id"]})
        current=next((t for t in view["tasks"] if t["id"]==task["id"]),None)
        if not current or current["status"] in ("done","failed","cancelled") or view["job"]["status"]!="open":
            state="committed" if current and current["status"]=="done" and current.get("attempt_id")==task.get("attempt_id") else "superseded"
            self.journal.save(task,state,result); return
        active=False
        if task.get("attempt_id"):
            active=self.backend.rpc("renew",{"task_id":task["id"],"attempt_id":task["attempt_id"],"seconds":self.seconds}).get("accepted",False)
        if not active:
            claimed=self.backend.rpc("claim",{"slot":task["slot"],"task_id":task["id"],"seconds":self.seconds})
            if not claimed: return  # Someone else is computing; keep local output but do not overwrite.
            if task_fingerprint(claimed)!=task_fingerprint(task):
                self.backend.rpc("fail",{"task_id":claimed["id"],"attempt_id":claimed["attempt_id"],"error":{"code":"cached_input_changed"}})
                self.journal.save(task,"superseded",result); return
            task=claimed; self.journal.save(task,"pending",result)
        self.backend.rpc("computed",{"task_id":task["id"],"attempt_id":task["attempt_id"]})
        cancel=threading.Event()
        with LeaseGuard(self.backend,task,self.seconds,cancel):
            files=[]
            for f in result["files"]:
                path=Path(f["local"])
                if not path.is_file(): raise FarmError("Local outbox file missing; do not erase outbox before synchronization")
                sha=digest(path)
                key=f"{self.backend.farm_id}/{self.backend.user_id}/{task['id']}/{task['attempt_id']}/{sha}-{safe_file(f['name'])}"
                if cancel.is_set(): return
                self.backend.upload(path,key,self.home/"uploads")
                files.append({"path":key,"sha256":sha,"size":path.stat().st_size,"name":f["name"],"role":f["role"]})
            output={k:v for k,v in result.items() if k not in ("files","fingerprint")}; output["files"]=files
            accepted=self.backend.rpc("finish",{"task_id":task["id"],"attempt_id":task["attempt_id"],"output":output})
            if accepted.get("accepted"): self.journal.save(task,"committed",result)

    def flush(self):
        # At most one uploader per node; avoids duplicate TUS PATCHes to the same URL.
        if not self.sync_lock.acquire(blocking=False): return
        try:
            for row in self.journal.entries(["pending","failure_pending"]):
                with self.task_lock(row["id"]):
                    latest=self.journal.entry(row["id"])
                    if latest and latest["state"] in ("pending","failure_pending"): self.flush_one(latest)
        finally: self.sync_lock.release()

    def execute_task(self,task,*,offline=False):
        # The uploader and executor may encounter the same re-leased task after a
        # network outage. Reuse durable output instead of destroying it by re-running.
        with self.task_lock(task["id"]):
            existing=self.journal.entry(task["id"])
            if existing and existing["state"]=="pending" and task_fingerprint(existing["task"])==task_fingerprint(task):
                if not offline:
                    self.journal.save(task,"pending",existing["result"])
                    self.upload_event.set()
                    with contextlib.suppress(OfflineError):
                        self.backend.rpc("computed",{"task_id":task["id"],"attempt_id":task["attempt_id"]})
                return
            return self._execute_task(task,offline=offline)

    def _execute_task(self,task,*,offline=False):
        if offline:
            task=dict(task); task["attempt_id"]=None
        work=self.home/"work"/task["id"]/str(task.get("attempt_id") or "offline")
        work.mkdir(parents=True,exist_ok=True)
        self.journal.save(task,"running")
        cancel=threading.Event()
        try:
            with LeaseGuard(self.backend,task,self.seconds,cancel):
                path=self.input_path(task) if offline else self.cache(task)
                if not path.is_file() or digest(path)!=self.input_blob(task)["sha256"]:
                    raise FarmError("Input not fully cached")
                result=execute(task,path,work,self.cfg,cancel)
                result["fingerprint"]=task_fingerprint(task)
                # Durable boundary is before upload or commit. Boot recovery reads this marker.
                write_json(work/"result.json",result)
                self.journal.save(task,"pending",result)
                for artifact in result["files"]:
                    file=Path(artifact["local"])
                    cached=self.home/"cache"/(digest(file)+file.suffix.lower())
                    cached.parent.mkdir(parents=True,exist_ok=True)
                    if not cached.exists():
                        temporary=cached.with_name(cached.name+"."+new_id()+".partial")
                        shutil.copyfile(file,temporary); temporary.replace(cached)
                self.upload_event.set()
                if not offline:
                    self.backend.rpc("computed",{"task_id":task["id"],"attempt_id":task["attempt_id"]})
        except OfflineError:
            # A failed input transfer is not an inference failure. A finished result remains pending.
            if self.journal.state(task["id"])=="running": self.journal.save(task,"cached")
            return
        except (FarmError,OSError,ValueError) as exc:
            if self.journal.state(task["id"])=="pending":
                # Upload/configuration failure is not an inference failure: preserve the outbox.
                self.journal.put("last_error",{"code":type(exc).__name__,"message":str(exc)[:300],"task":task["id"]})
                return
            error={"code":"execution_failed","message":str(exc)[:300]}
            self.journal.save(task,"failure_pending" if task.get("attempt_id") else "failed",error)
            if not offline:
                with contextlib.suppress(OfflineError,FarmError): self.flush()

    def offline_step(self,slot):
        if not self.cfg.get("offline_speculation",False): return False
        # Pure input->output work only, bounded by the prefetch reservoir; never create jobs,
        # approve assets, run arbitrary shell instructions, or advance the authoritative DAG offline.
        for row in self.journal.entries(["cached"]):
            task=row["task"]
            if task["slot"]!=slot or task["capability"] not in self.caps: continue
            if time.time()-row["updated"]>3600: continue
            if not self.input_path(task).is_file(): continue
            self.execute_task(task,offline=True); return True
        return False

    def can_run_slot(self,slot):
        return can_run(slot,self.cfg,self.stats)

    def step(self,slot):
        if (self.home/"PAUSED").exists() or (self.home/"STOP").exists(): return False
        if not self.can_run_slot(slot): return False
        try:
            self.upload_event.set()
            if len(self.journal.entries(["pending"]))>=int(self.cfg.get("max_pending_results",4)): return False
            task=self.backend.rpc("claim",{"slot":slot,"seconds":self.seconds})
            if task:
                self.execute_task(task); return True
            self.prefetch(slot); return False
        except OfflineError:
            return self.offline_step(slot)

    def run_forever(self):
        with ProcessLock(self.home/"worker.lock"):
            (self.home/"STOP").unlink(missing_ok=True)
            def maintenance():
                delay=3
                while not self.shutdown.is_set():
                    try:
                        self.refresh()
                        for slot in ("gpu","cpu"):
                            if not self.shutdown.is_set(): self.prefetch(slot)
                        delay=10
                    except (OfflineError,FarmError,OSError) as e:
                        self.journal.put("last_error",{"code":type(e).__name__,"message":str(e)[:300],"time":time.time()})
                        delay=min(60,delay*1.5)
                    self.shutdown.wait(delay+random.random())
            def uploader():
                while not self.shutdown.is_set():
                    try: self.flush()
                    except (FarmError,OSError,ValueError) as e:
                        self.journal.put("last_error",{"code":type(e).__name__,"message":str(e)[:300]})
                    self.upload_event.wait(5); self.upload_event.clear()
            def loop(slot):
                while not self.shutdown.is_set():
                    if (self.home/"STOP").exists(): self.shutdown.set(); break
                    try:
                        did_work=self.step(slot)
                    except (FarmError,OSError,ValueError) as e:
                        self.journal.put("last_error",{"code":type(e).__name__,"message":str(e)[:300]})
                        did_work=False
                    if not did_work: self.shutdown.wait(3+random.random()*2)
            # Autostart may run before Wi-Fi: offline startup is normal, not fatal.
            self.stats=telemetry(self.cfg); self.caps=capabilities(self.cfg)
            threads=[threading.Thread(target=maintenance,daemon=True),threading.Thread(target=uploader,daemon=True),threading.Thread(target=loop,args=("gpu",)),threading.Thread(target=loop,args=("cpu",))]
            for thread in threads: thread.start()
            try:
                while not self.shutdown.wait(1): pass
            except KeyboardInterrupt:
                self.shutdown.set()  # Graceful drain; STOP prevents new claims, not durable local results.
            for thread in threads[2:]: thread.join()
            with contextlib.suppress(OfflineError,FarmError): self.flush()
