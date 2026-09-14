from __future__ import annotations
import json, re
from pathlib import Path
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from .common import CFError, now, canonical, sha, atomic_json, file_sha, safe_relative
from .db import users, requests, nodes, events, audit, nonces, revocations, jobs, releases, record
from .device import verify_headers
from .service import Service, ALLOWED_GRANTS
from .registry import profile_digest, ADAPTERS, get_profile
from .audio import AUDIO_PROFILES
from . import __version__
from .updates import latest_update, update_artifact

class Body(BaseModel): model_config=ConfigDict(extra="forbid")
class Join(Body):
    kind: str
    payload: dict
    idempotency_key: str=Field(min_length=8,max_length=100)
class Decide(Body):
    approve: bool
    grant: str|None=None
class Desired(Body):
    profiles: list[str]=Field(max_length=50)
    experimental: bool=False
    expected_revision: int=Field(ge=0)
class Heartbeat(Body):
    inventory: dict
    capabilities: list[dict]=Field(max_length=50)
class Submit(Body):
    profile_id: str
    release_id: str|None=None
    spec: dict
    idempotency_key: str=Field(min_length=8,max_length=100)
class Finish(Body):
    attempt_id: str
    output: dict|None=None
    error: dict|None=None
class Renew(Body): attempt_id: str
class UserChange(Body):
    status: str|None=None
    grants: list[str]|None=None
class NodeStatus(Body): status: str
class CentralRPC(Body):
    action: str
    args: dict = Field(default_factory=dict)
class Engines(Body):
    engines: list[str] = Field(max_length=3)

class LimitBody:
    def __init__(self,app,limit=17*1024*1024): self.app,self.limit=app,limit
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http": return await self.app(scope,receive,send)
        received=0
        async def checked_receive():
            nonlocal received
            msg=await receive();received+=len(msg.get("body",b""))
            if received>self.limit: raise CFError("body_too_large","Body exceeds the request size limit",413)
            return msg
        await self.app(scope,checked_receive,send)

def create_app(db,registry,verifier,*,artifact_root,auth_config=None,release_trust=None,bridge=None,update_root=None):
    app=FastAPI(title="ClayFarm Control Plane",version=__version__)
    # A 120s 44.1kHz stereo PCM master is about 21MiB.  Keep one bounded
    # request limit for both local and central modes so valid BGM results are
    # not rejected before the per-artifact check.
    app.add_middleware(LimitBody,limit=64*1024*1024)
    service=Service(db,registry);root=Path(artifact_root);root.mkdir(parents=True,exist_ok=True)
    updates=Path(update_root) if update_root is not None else root.parent/"updates"
    updates.mkdir(parents=True,exist_ok=True)
    app.state.service=service;app.state.db=db
    def artifact_suffix(profile_id):
        kinds=set(get_profile(registry,profile_id).get("asset_kinds",()))
        if "sfx" in kinds or "music" in kinds: return "wav"
        return "svg" if profile_id=="deterministic-ui" else "png"
    def development_queue():
        if bridge:
            raise CFError('central_queue_required','Use the central 3D task API; the parallel development queue is disabled',409)
    @app.exception_handler(CFError)
    async def error(_,exc): return JSONResponse({"error":{"code":exc.code,"message":exc.message}},status_code=exc.status)
    @app.exception_handler(IntegrityError)
    async def conflict(_,exc): return JSONResponse({"error":{"code":"concurrent_conflict","message":"Concurrent request conflict; retry with the same idempotency key"}},status_code=409)
    async def principal(req:Request):
        token=req.headers.get("authorization","")
        if not token.startswith("Bearer "): raise CFError("login_required","User login required",401)
        identity=verifier(token[7:]);member=service.member(identity)
        return {**member,"aal":identity.get("aal","aal1"),"session_id":identity.get("session_id"),"expires_at":identity.get("expires_at")}
    async def admin(user=Depends(principal)):
        if user["role"]!="admin": raise CFError("admin_required","Administrator role required",403)
        if user["aal"]!="aal2": raise CFError("mfa_required","Administrator operations require AAL2 MFA",403)
        return user
    async def device_any(req:Request):
        nid=req.headers.get("x-cf-node","")
        node=db.read(nodes,id=nid)
        if not node: raise CFError("unknown_device","Device registration required",401)
        owner=db.read(users,id=node["owner"])
        if not owner or owner["status"]!="active": raise CFError("owner_suspended","Device owner is not active",403)
        if node["status"] in ("revoked","rejected"): raise CFError("device_revoked","Node access revoked",403)
        target=req.url.path+("?"+req.url.query if req.url.query else "")
        nonce=verify_headers(node["public_key"],req.method,target,await req.body(),req.headers)
        try:
            with db.transaction() as c:
                c.execute(nonces.delete().where(nonces.c.created_at<now()-600))
                c.execute(nonces.insert().values(node_id=nid,nonce=nonce,created_at=now()))
        except IntegrityError: raise CFError("replayed_device_proof","Device signature nonce already used",401)
        return dict(node)
    async def device(node=Depends(device_any)):
        if node["status"]!="active": raise CFError("node_not_active","Node is pending, paused, or revoked",403)
        return node
    def view_job(jid,user):
        row=db.read(jobs,id=jid)
        if not row or (row["owner"]!=user["id"] and user["role"]!="admin"): raise CFError("not_found","Job not found",404)
        return dict(row)
    @app.get("/health")
    def health(): return {"status":"ok","version":__version__,"central_queue_configured":bridge is not None,"parallel_queue_enabled":bridge is None,"queue_backend":"public.cf_jobs/cf_tasks" if bridge else "development_fixture_queue"}
    @app.get("/v1/config")
    def config(): return auth_config or {"auth_provider":"test_fixture_only"}
    @app.get("/v1/updates/check")
    def updates_check(channel:str="stable",platform_os:str|None=None,platform_arch:str|None=None):
        envelope=latest_update(updates,release_trust or {},channel=channel,platform_os=platform_os,platform_arch=platform_arch)
        return {"product":"clayfarm-control","current_version":__version__,"channel":channel,"update_available":envelope is not None,"latest":envelope}
    @app.get("/v1/updates/artifacts/{release_id}")
    def update_download(release_id:str):
        path,manifest=update_artifact(updates,release_trust or {},release_id)
        return FileResponse(path,media_type="application/octet-stream",filename=path.name,headers={"X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; sandbox","X-ClayFarm-Release":manifest["id"]})
    @app.get("/v1/me")
    def me(user=Depends(principal)): return user
    @app.post("/v1/sessions/revoke")
    def revoke(user=Depends(principal)):
        if not user.get("session_id"): raise CFError("session_missing","Session ID missing")
        with db.transaction() as c:
            # Serialize revocation with central operations holding a shared
            # authorization lock for this user, including in-flight transfers.
            c.execute(select(users.c.id).where(users.c.id==user['id']).with_for_update()).first()
            if not c.execute(select(revocations).where(revocations.c.session_id==user["session_id"])).first():
                c.execute(revocations.insert().values(session_id=user["session_id"],expires_at=user.get("expires_at") or now()+3600))
        return {"revoked":True}
    @app.post("/v1/requests")
    def join(body:Join,user=Depends(principal)): return service.request_access(user,body.kind,body.payload,body.idempotency_key)
    @app.get("/v1/requests")
    def own_requests(user=Depends(principal)):
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(requests).where(requests.c.owner==user["id"]).order_by(requests.c.created_at.desc()).limit(200)).mappings()]
    @app.get("/v1/admin/requests")
    def pending(state:str="pending",user=Depends(admin)):
        if state not in ("pending","approved","rejected"): raise CFError("invalid_state","Unknown request state")
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(requests).where(requests.c.state==state).order_by(requests.c.created_at).limit(200)).mappings()]
    @app.post("/v1/admin/requests/{rid}/decision")
    def decision(rid:str,body:Decide,user=Depends(admin)): return service.decide(user,rid,body.approve,body.grant)
    @app.get("/v1/admin/users")
    def user_list(user=Depends(admin)):
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(users).limit(500)).mappings()]
    @app.patch("/v1/admin/users/{target}")
    def user_change(target:str,body:UserChange,user=Depends(admin)):
        if body.status not in (None,"active","suspended"): raise CFError("invalid_status","Unknown status")
        if body.grants is not None and set(body.grants)-ALLOWED_GRANTS: raise CFError("invalid_grant","Unknown grant")
        with db.transaction() as c:
            old=c.execute(select(users).where(users.c.id==target).with_for_update()).mappings().first()
            if not old: raise CFError("not_found","Member not found",404)
            if old["role"]=="admin" and body.status=="suspended": raise CFError("admin_lockout_protection","Admin suspension requires the server-side recovery procedure")
            changes=body.model_dump(exclude_none=True)
            if changes: c.execute(users.update().where(users.c.id==target).values(**changes))
            record(c,user["id"],"member_changed",target,changes,target)
        return {"id":target,**changes}
    @app.get("/v1/nodes")
    def node_list(user=Depends(principal)):
        with db.engine.connect() as c:
            q=select(nodes)
            if user["role"]!="admin": q=q.where(nodes.c.owner==user["id"])
            return [dict(x) for x in c.execute(q.limit(200)).mappings()]
    @app.get("/v1/node/status")
    def node_status(node=Depends(device_any)): return {k:node[k] for k in ("id","name","status","desired","last_seen")}
    @app.put("/v1/admin/nodes/{nid}/desired")
    def node_desired(nid:str,body:Desired,user=Depends(admin)): return service.desired(user,nid,body.profiles,body.experimental,body.expected_revision)
    @app.patch("/v1/nodes/{nid}/status")
    def change_node_status(nid:str,body:NodeStatus,user=Depends(principal)):
        row=db.read(nodes,id=nid)
        if not row or (row["owner"]!=user["id"] and user["role"]!="admin"): raise CFError("not_found","Node not found",404)
        if user["role"]=="admin" and user["aal"]!="aal2": raise CFError("mfa_required","AAL2 required",403)
        if row["status"] in ("pending","rejected","revoked") or body.status not in ("active","paused","revoked"): raise CFError("invalid_transition","Cannot bypass participation approval",409)
        with db.transaction() as c:
            c.execute(nodes.update().where(nodes.c.id==nid).values(status=body.status))
            record(c,user["id"],"node_status_changed",nid,{"status":body.status},row["owner"])
        return {"id":nid,"status":body.status}
    @app.post("/v1/node/heartbeat")
    def beat(body:Heartbeat,node=Depends(device)): return service.heartbeat(node,body.inventory,body.capabilities)
    @app.get("/v1/catalog")
    def catalog(user=Depends(principal)):
        return {"registry_revision":registry["registry_revision"],"profiles":[{**p,"adapter_implemented":p["id"] in ADAPTERS,"central_queue_supported":not bridge or p["id"] not in AUDIO_PROFILES,"profile_digest":profile_digest(registry,p),"access_allowed":"creator-basic" in user["grants"] and (p["lane"]=="candidate" or "experimental" in user["grants"])} for p in registry["profiles"]]}
    @app.get("/v1/notifications")
    def notifications(after:int=0,user=Depends(principal)):
        audience=[user["id"]]+(["admins"] if user["role"]=="admin" else [])
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(events).where(events.c.audience.in_(audience),events.c.id>max(0,after)).order_by(events.c.id).limit(200)).mappings()]
    @app.get("/v1/admin/audit")
    def audit_log(after:int=0,user=Depends(admin)):
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(audit).where(audit.c.id>max(0,after)).order_by(audit.c.id).limit(200)).mappings()]
    @app.post("/v1/jobs")
    def submit(body:Submit,user=Depends(principal)):
        development_queue()
        return service.submit(user,body.profile_id,body.spec,body.idempotency_key,body.release_id)
    @app.get("/v1/jobs")
    def own_jobs(user=Depends(principal)):
        if bridge: return bridge.rpc(user,False,'list',{})
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(jobs).where(jobs.c.owner==user["id"]).order_by(jobs.c.created_at.desc()).limit(200)).mappings()]
    @app.get("/v1/jobs/{jid}")
    def get_job(jid:str,user=Depends(principal)):
        if bridge: return bridge.rpc(user,False,'get',{'id':jid})
        return view_job(jid,user)
    @app.post("/v1/jobs/{jid}/cancel")
    def cancel(jid:str,user=Depends(principal)):
        if bridge: return bridge.rpc(user,False,'cancel',{'id':jid})
        view_job(jid,user)
        with db.transaction() as c:
            result=c.execute(jobs.update().where(jobs.c.id==jid,jobs.c.state.in_(["queued","running"])).values(state="cancelled"))
            record(c,user["id"],"job_cancelled",jid)
        return {"id":jid,"cancelled":bool(result.rowcount)}
    @app.get("/v1/jobs/{jid}/artifact")
    def artifact(jid:str,user=Depends(principal)):
        development_queue()
        job=view_job(jid,user)
        if job["state"]!="done" or not job.get("output"): raise CFError("artifact_not_ready","Artifact is not ready",409)
        p=root/job["id"]/job["attempt_id"]/job["output"]["name"]
        if not p.is_file() or file_sha(p)!=job["output"]["sha256"]: raise CFError("artifact_missing","Artifact missing or corrupted",500)
        return FileResponse(p,media_type="application/octet-stream",filename=job["output"]["name"],headers={"X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; sandbox"})
    @app.post("/v1/node/jobs/claim")
    def claim(node=Depends(device)):
        development_queue()
        return service.claim(node)
    @app.post("/v1/node/jobs/{jid}/renew")
    def renew(jid:str,body:Renew,node=Depends(device)):
        development_queue()
        return service.finish(node,jid,body.attempt_id,renew=True)
    @app.put("/v1/node/jobs/{jid}/artifact")
    async def upload(jid:str,attempt:str,req:Request,node=Depends(device)):
        development_queue()
        job=db.read(jobs,id=jid)
        if not job or job["node_id"]!=node["id"] or job["attempt_id"]!=attempt or job["state"]!="running" or job["lease_until"]<now(): raise CFError("stale_attempt","Only the current lease may upload",409)
        data=await req.body()
        if not 1<=len(data)<=48*1024*1024: raise CFError("artifact_size","Artifact must be 1 byte..48MiB",413)
        suffix=artifact_suffix(job["profile_id"])
        if suffix=="png" and not data.startswith(b"\x89PNG\r\n\x1a\n"): raise CFError("artifact_format","PNG header missing")
        if suffix=="wav" and not(data[:4]==b"RIFF" and data[8:12]==b"WAVE"): raise CFError("artifact_format","WAV header missing")
        path=root/jid/attempt/("asset."+suffix);path.parent.mkdir(parents=True,exist_ok=True)
        from clayfarm.util import atomic_bytes
        atomic_bytes(path,data)
        return {"name":path.name,"sha256":sha(data),"size":len(data)}
    @app.post("/v1/node/jobs/{jid}/finish")
    def finish(jid:str,body:Finish,node=Depends(device)):
        development_queue()
        job=db.read(jobs,id=jid)
        if body.output:
            if not job or job["node_id"]!=node["id"] or job["attempt_id"]!=body.attempt_id: raise CFError("stale_attempt","Invalid owner",409)
            expected="asset."+artifact_suffix(job["profile_id"])
            if set(body.output)!={"name","sha256","size"} or body.output["name"]!=expected: raise CFError("invalid_output","Unexpected artifact manifest")
            p=root/jid/body.attempt_id/expected
            if not p.is_file() or file_sha(p)!=body.output["sha256"] or p.stat().st_size!=body.output["size"]: raise CFError("invalid_output","Artifact manifest does not match stored bytes")
        if bool(body.output)==bool(body.error): raise CFError("invalid_result","Provide exactly one of output or error")
        if body.error and len(canonical(body.error))>4096: raise CFError("error_too_large","Error detail exceeds 4KiB")
        return service.finish(node,jid,body.attempt_id,body.output,body.error)
    @app.post("/v1/admin/releases")
    def publish(body:dict,user=Depends(admin)):
        from .releases import verify_manifest
        if "release-manager" not in user["grants"]: raise CFError("release_role_required","Release manager grant required",403)
        m=verify_manifest(body,release_trust or {})
        with db.transaction() as c:
            old=c.execute(select(releases).where(releases.c.id==m["id"])).mappings().first()
            if old:
                if old["envelope"]!=body: raise CFError("release_conflict","Immutable release ID already exists",409)
                return {"id":m["id"],"replayed":True}
            c.execute(releases.insert().values(id=m["id"],envelope=body,published_by=user["id"],created_at=now()))
            record(c,user["id"],"release_published",m["id"],{},"admins")
        return {"id":m["id"],"state":"published","automatically_executed":False}
    @app.get("/v1/releases")
    def release_list(user=Depends(principal)):
        with db.engine.connect() as c: return [dict(x) for x in c.execute(select(releases).order_by(releases.c.created_at.desc()).limit(100)).mappings()]
    if bridge:
        @app.post('/v1/central/rpc')
        def central_rpc(body:CentralRPC,user=Depends(principal)):
            return bridge.rpc(user,False,body.action,body.args)
        @app.post('/v1/node/central/rpc')
        def node_rpc(body:CentralRPC,node=Depends(device)):
            return bridge.rpc(node,True,body.action,body.args)
        @app.put('/v1/admin/nodes/{nid}/engines')
        def engines(nid:str,body:Engines,user=Depends(admin)):
            return bridge.set_engines(user,nid,body.engines)
        @app.put('/v1/central/artifacts')
        async def put_input(key:str,req:Request,user=Depends(principal)):
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(bridge.upload,user,False,key,await req.body())
        @app.put('/v1/node/central/artifacts')
        async def put_output(key:str,req:Request,node=Depends(device)):
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(bridge.upload,node,True,key,await req.body())
        @app.get('/v1/central/artifacts')
        def get_output(key:str,user=Depends(principal)):
            return Response(bridge.download(user,False,key),media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})
        @app.get('/v1/node/central/artifacts')
        def get_input(key:str,node=Depends(device)):
            return Response(bridge.download(node,True,key),media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})
    return app
