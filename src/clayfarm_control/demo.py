"""Local integration fixture: real API/database/crypto/CPU generation, mock human Auth."""
from __future__ import annotations
import json, time
from pathlib import Path
from fastapi.testclient import TestClient
from .api import create_app
from .db import Database
from .registry import load_registry
from .common import atomic_json, CFError, uid, file_sha
from .client import Client
from .vault import MemoryVault
from .device import new_key
from .inventory import probe
from .models import Models
from .agent import Agent

ADMIN="00000000-0000-4000-8000-000000000001"
USER="00000000-0000-4000-8000-000000000002"
OTHER="00000000-0000-4000-8000-000000000003"

class FixtureVerifier:
    def __call__(self,token):
        identities={"fixture-admin":(ADMIN,"admin@example.test","aal2"),"fixture-admin-aal1":(ADMIN,"admin@example.test","aal1"),"fixture-user":(USER,"user@example.test","aal1"),"fixture-other":(OTHER,"other@example.test","aal1")}
        if token not in identities:raise CFError("invalid_test_identity","Unknown fixture identity",401)
        id,email,aal=identities[token]
        return {"id":id,"email":email,"aal":aal,"session_id":token+"-session","expires_at":time.time()+86400}

def fixture_client(home,app,token=None):
    home=Path(home);atomic_json(home/"control.json",{"server":"http://127.0.0.1:8765"})
    vault=MemoryVault()
    if token:vault.put("human-session",{"access_token":token,"expires_at":time.time()+86400})
    c=Client(home,vault=vault);c.http.close();c.http=TestClient(app)
    return c

def demo(out):
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise CFError("demo_output_exists","Use an empty demo directory")
    out.mkdir(parents=True,exist_ok=True)
    db=Database("sqlite:///"+str(out/"control.db"));db.init();db.bootstrap_admin(ADMIN,"admin@example.test")
    registry=load_registry();app=create_app(db,registry,FixtureVerifier(),artifact_root=out/"server-artifacts")
    admin=fixture_client(out/"admin",app,"fixture-admin")
    user=fixture_client(out/"user",app,"fixture-user")
    request=user.call("POST","/v1/requests",{"kind":"access","payload":{"requested_grant":"creator-basic","reason":"Local integration test"},"idempotency_key":"demo-access-1"})
    before=admin.call("GET","/v1/notifications?after=0")
    admin.call("POST",f'/v1/admin/requests/{request["id"]}/decision',{"approve":True})
    key=new_key();user.vault.put("node-key",key)
    node=user.call("POST","/v1/requests",{"kind":"node","payload":{"name":"CPU demo node","public_key":key["public"],"inventory":probe()},"idempotency_key":"demo-node-01"})
    user.config["node_id"]=node["id"];atomic_json(user.home/"control.json",user.config)
    admin.call("POST",f'/v1/admin/requests/{node["id"]}/decision',{"approve":True})
    desired=admin.call("PUT",f'/v1/admin/nodes/{node["id"]}/desired',{"profiles":["deterministic-ui","procedural-sfx"],"expected_revision":0,"experimental":False})
    atomic_json(user.home/"policy.json",{"auto_install_builtin":True})
    agent=Agent(user.home,user);reconcile=agent.reconcile()
    produced=[]
    for pid,spec in [("deterministic-ui",{"text":"ClayFarm READY"}),("procedural-sfx",{"effect":"impact","seconds":.35,"seed":7})]:
        job=user.call("POST","/v1/jobs",{"profile_id":pid,"spec":spec,"idempotency_key":"demo-job-"+pid})
        agent.step();done=user.call("GET",f'/v1/jobs/{job["id"]}')
        if done["state"]!="done":raise CFError("demo_failed","Generated job did not finish")
        data=user.call("GET",f'/v1/jobs/{job["id"]}/artifact',download=True)
        path=out/"outputs"/done["output"]["name"];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        produced.append({"profile_id":pid,"file":str(path),"sha256":file_sha(path),"bytes":len(data),"state":done["state"]})
    report={"auth":"in-process fixture only, NOT real Supabase email/MFA","network":"in-process HTTP API via TestClient","database":"real SQLite transactions","node_auth":"real Ed25519 per-request signature and replay guard","notification_records_before_approval":len(before),"enrollment":"one approval, no shared enrollment/password file","desired":desired,"reconcile":reconcile,"outputs":produced,"gpu_models_executed":False,"legacy_queue_migrated":False}
    atomic_json(out/"report.json",report)
    admin.http.close();user.http.close();db.engine.dispose()
    return report
