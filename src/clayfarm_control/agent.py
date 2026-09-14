"""Opt-in loop: reconcile builtin desired profiles and execute a fenced v0.3 job."""
from __future__ import annotations
import threading, time, shutil
from pathlib import Path
from .common import CFError, read_json, atomic_json
from .inventory import probe
from .models import Models
from .registry import load_registry, ADAPTERS
from clayfarm.util import ProcessLock

class Agent:
    def __init__(self,home,client):
        self.home=Path(home);self.client=client;self.models=Models(home,load_registry());self.root=self.home/"outbox";self.root.mkdir(parents=True,exist_ok=True)
    def heartbeat(self):
        states=self.models.states()
        runtime_python=next((x["python"] for x in states.values() if x.get("status")=="verified" and x.get("backend") in ("mps","cuda")),None)
        inv=probe(python=runtime_python,deep=True)
        policy=read_json(self.home/"policy.json",{})
        inv["policy"]={"allow_battery":bool(policy.get("allow_battery",False))}
        return self.client.call("POST","/v1/node/heartbeat",{"inventory":inv,"capabilities":self.models.capabilities()},node=True)
    def reconcile(self):
        state=self.client.call("GET","/v1/node/status",node=True)
        if state["status"]!="active": return {"status":state["status"]}
        policy=read_json(self.home/"policy.json",{})
        installed=[];blocked=[]
        for pid in state["desired"]["profiles"]:
            if not policy.get("auto_install_builtin",False): blocked.append({"profile_id":pid,"reason":"local_policy_requires_opt_in"});continue
            if ADAPTERS.get(pid) not in ("builtin_ui","builtin_sfx"):
                blocked.append({"profile_id":pid,"reason":"signed_model_recipe_and_local_license_consent_required"});continue
            s=self.models.builtin_sync(pid)
            if s["status"]!="verified": self.models.verify(pid)
            installed.append(pid)
        self.heartbeat()
        return {"installed":installed,"blocked":blocked,"desired_revision":state["desired"]["revision"]}
    def flush(self):
        results=[]
        for f in self.root.glob("*/*/pending.json"):
            p=read_json(f);jid,attempt=p["job_id"],p["attempt_id"]
            try:
                manifest=p.get("uploaded_manifest")
                if manifest is None:
                    manifest=self.client.call("PUT",f"/v1/node/jobs/{jid}/artifact?attempt={attempt}",node=True,raw=Path(p["artifact"]).read_bytes())
                    p["uploaded_manifest"]=manifest;atomic_json(f,p)
                self.client.call("POST",f"/v1/node/jobs/{jid}/finish",{"attempt_id":attempt,"output":manifest},node=True)
                atomic_json(f.with_name("committed.json"),{**p,"output":manifest});f.unlink();results.append(jid)
            except CFError as e:
                if e.code=="stale_attempt":
                    atomic_json(f.with_name("stale.json"),{**p,"reason":e.code});f.unlink()
                else: raise
        return results
    def step(self):
        self.flush();self.heartbeat()
        job=self.client.call("POST","/v1/node/jobs/claim",{},node=True).get("job")
        if not job:return {"status":"idle"}
        work=self.root/job["id"]/job["attempt_id"]
        work.mkdir(parents=True,exist_ok=True)
        stop=threading.Event();cancel_compute=threading.Event();lease_lost=[]
        def renew():
            while not stop.wait(30):
                try:self.client.call("POST",f'/v1/node/jobs/{job["id"]}/renew',{"attempt_id":job["attempt_id"]},node=True)
                except CFError as e:
                    if e.code!="offline":lease_lost.append(e.code);cancel_compute.set();return
        thread=threading.Thread(target=renew,daemon=True);thread.start()
        try:
            result=self.models.generate(job["profile_id"],job["spec"],work,cancel_compute)
            atomic_json(work/"pending.json",{"job_id":job["id"],"attempt_id":job["attempt_id"],"artifact":result["artifact"],"lease_lost":lease_lost})
        except CFError as e:
            try:self.client.call("POST",f'/v1/node/jobs/{job["id"]}/finish',{"attempt_id":job["attempt_id"],"error":{"code":e.code,"message":e.message[:500]}},node=True)
            except CFError:pass
            raise
        finally:stop.set();thread.join(timeout=2)
        self.flush()
        return {"status":"computed","job_id":job["id"],"delivery":"see outbox receipts"}
    def run(self,once=False):
        with ProcessLock(self.home/"control-worker.lock"):
            while True:
                if (self.home/"CONTROL_STOP").exists():
                    (self.home/"CONTROL_STOP").unlink();return {"stopped":True}
                try:
                    state=self.client.call("GET","/v1/node/status",node=True)
                    if state["status"]!="active":
                        if once:return {"status":state["status"]}
                        time.sleep(15);continue
                    self.reconcile()
                    result=self.step()
                    if once:return result
                    if result["status"]=="idle":time.sleep(5)
                except CFError as e:
                    if once or e.code not in ("offline","node_not_active"):raise
                    time.sleep(15)
