from __future__ import annotations
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.exc import IntegrityError
from .common import CFError, uid, now, canonical, sha
from .db import users, requests, nodes, events, audit, jobs, nonces, revocations, releases, record
from .device import public_key_valid
from .registry import get_profile, profile_digest, ADAPTERS, KINDS

ALLOWED_GRANTS={"creator-basic","experimental","release-manager"}

class Service:
    def __init__(self,db,registry): self.db,self.registry=db,registry
    def member(self,identity):
        with self.db.transaction() as c:
            row=c.execute(select(users).where(users.c.id==identity["id"])).mappings().first()
            if not row:
                c.execute(users.insert().values(id=identity["id"],email=identity["email"],role="member",status="active",grants=[],created_at=now()))
                row=c.execute(select(users).where(users.c.id==identity["id"])).mappings().first()
            if row["status"]!="active": raise CFError("account_suspended","Account is not active",403)
            sid=identity.get("session_id")
            if sid and c.execute(select(revocations).where(revocations.c.session_id==sid)).first(): raise CFError("session_revoked","Session was revoked",401)
            return dict(row)
    def request_access(self,user,kind,payload,key):
        if kind not in ("access","node"): raise CFError("invalid_request","Unknown request kind")
        if not 8<=len(key)<=100: raise CFError("idempotency_required","Use a stable idempotency key of 8-100 characters")
        if len(canonical(payload))>32768: raise CFError("payload_too_large","Request metadata exceeds 32KiB")
        digest=sha(canonical({"kind":kind,"payload":payload}))
        with self.db.transaction() as c:
            # Serializes duplicate requests from a single principal on PostgreSQL as well.
            c.execute(select(users).where(users.c.id==user["id"]).with_for_update()).first()
            prior=c.execute(select(requests).where(requests.c.owner==user["id"],requests.c.idempotency_key==key)).mappings().first()
            if prior:
                if prior["payload_hash"]!=digest: raise CFError("idempotency_conflict","Key was already used with another payload",409)
                return dict(prior)
            count=c.execute(select(func.count()).select_from(requests).where(requests.c.owner==user["id"],requests.c.state=="pending")).scalar_one()
            if count>=5: raise CFError("request_limit","Five pending requests already exist",429)
            rid=uid()
            if kind=="node":
                allowed={"name","public_key","inventory"}
                if set(payload)-allowed or not isinstance(payload.get("name"),str) or not 1<=len(payload["name"])<=100: raise CFError("invalid_node","Node name/key/inventory required")
                public_key_valid(payload.get("public_key",""))
                old=c.execute(select(nodes).where(nodes.c.public_key==payload["public_key"])).first()
                if old: raise CFError("device_key_registered","Device key is already registered",409)
                c.execute(nodes.insert().values(id=rid,owner=user["id"],name=payload["name"],public_key=payload["public_key"],status="pending",inventory=payload.get("inventory",{}),capabilities=[],desired={"revision":0,"profiles":[],"experimental":False,"core_release":None},created_at=now()))
            else:
                if set(payload)-{"reason","requested_grant"} or payload.get("requested_grant","creator-basic") not in {"creator-basic","experimental"}: raise CFError("invalid_grant","Request creator-basic or experimental")
            c.execute(requests.insert().values(id=rid,owner=user["id"],kind=kind,payload=payload,payload_hash=digest,idempotency_key=key,state="pending",created_at=now()))
            record(c,user["id"],"request_created",rid,{"kind":kind,"requester":user["email"]},"admins")
            return dict(c.execute(select(requests).where(requests.c.id==rid)).mappings().one())
    def decide(self,admin,rid,approve,grant=None):
        with self.db.transaction() as c:
            row=c.execute(select(requests).where(requests.c.id==rid).with_for_update()).mappings().first()
            if not row: raise CFError("not_found","Request does not exist",404)
            state="approved" if approve else "rejected"
            decision={"approved":approve,"grant":grant}
            if row["state"]!="pending":
                if row["state"]==state and row["decision"].get("decision")==decision: return {"id":rid,"state":state,"replayed":True}
                raise CFError("already_decided","Request has a different final decision",409)
            if approve and row["kind"]=="access":
                chosen=grant or row["payload"].get("requested_grant","creator-basic")
                if chosen not in ALLOWED_GRANTS: raise CFError("invalid_grant","Unknown grant")
                member=c.execute(select(users).where(users.c.id==row["owner"]).with_for_update()).mappings().one()
                c.execute(users.update().where(users.c.id==row["owner"]).values(grants=sorted(set(member["grants"]+[chosen]))))
            elif row["kind"]=="node":
                c.execute(nodes.update().where(nodes.c.id==rid).values(status="active" if approve else "rejected"))
            c.execute(requests.update().where(requests.c.id==rid).values(state=state,decision={"actor":admin["id"],"at":now(),"decision":decision}))
            record(c,admin["id"],"request_"+state,rid,{"kind":row["kind"]},row["owner"])
            return {"id":rid,"state":state,"node_execution_ready":False if row["kind"]=="node" else None}
    def desired(self,admin,nid,profiles,experimental,expected):
        profiles=list(dict.fromkeys(profiles))
        for name in profiles:
            p=get_profile(self.registry,name)
            if p["lane"]!="candidate" and not experimental: raise CFError("experimental_required","Experimental profiles need explicit opt-in")
        with self.db.transaction() as c:
            n=c.execute(select(nodes).where(nodes.c.id==nid).with_for_update()).mappings().first()
            if not n: raise CFError("not_found","Node not found",404)
            if n["desired"]["revision"]!=expected: raise CFError("revision_conflict","Read the latest node revision before updating",409)
            value={**n["desired"],"revision":expected+1,"profiles":profiles,"experimental":experimental}
            c.execute(nodes.update().where(nodes.c.id==nid).values(desired=value))
            record(c,admin["id"],"node_desired_changed",nid,{"revision":value["revision"],"profiles":profiles},n["owner"])
            return value
    def heartbeat(self,node,inventory,capabilities):
        desired=node["desired"]
        accepted=[]
        for cap in capabilities:
            p=get_profile(self.registry,cap.get("profile_id",""))
            if p["id"] not in desired["profiles"]: continue
            if cap.get("status")!="verified" or p["id"] not in ADAPTERS: continue
            if cap.get("profile_digest")!=profile_digest(self.registry,p): continue
            if cap.get("backend")!=p["backend"]: continue
            # No readiness for a merely downloaded model, nor unmeasured profiles.
            if cap.get("peak_host_bytes") is None or (p["backend"]!="cpu" and cap.get("peak_device_bytes") is None): continue
            if not cap.get("artifact_sha256") or not cap.get("adapter_digest") or not cap.get("tested_at"): continue
            accepted.append(cap)
        with self.db.transaction() as c:
            c.execute(nodes.update().where(nodes.c.id==node["id"]).values(inventory=inventory,capabilities=accepted,last_seen=now()))
        return {"node_id":node["id"],"accepted_capabilities":len(accepted),"desired":desired,"status":node["status"]}
    def submit(self,user,profile_id,spec,key,release_id=None):
        if "creator-basic" not in user["grants"]: raise CFError("approval_required","Asset request permission requires approval",403)
        p=get_profile(self.registry,profile_id)
        if profile_id not in ADAPTERS: raise CFError("adapter_not_implemented","This profile is a catalog candidate, not an executable path",422)
        if p["lane"]!="candidate" and "experimental" not in user["grants"]: raise CFError("experimental_required","Experimental access is not approved",403)
        from .adapters.builtin import validate_spec
        validate_spec(profile_id,spec)
        if p.get("model_id"):
            if not release_id: raise CFError("pinned_release_required","Select an approved, immutable model release",422)
            release=self.db.read(releases,id=release_id)
            if not release or release["envelope"]["signed"].get("profile_digest")!=profile_digest(self.registry,p): raise CFError("invalid_release","Release does not match this profile",422)
        else: release_id="bundled-0.3.0.dev1"
        digest=sha(canonical({"profile_id":profile_id,"spec":spec,"release_id":release_id}))
        with self.db.transaction() as c:
            c.execute(select(users).where(users.c.id==user["id"]).with_for_update()).first()
            prior=c.execute(select(jobs).where(jobs.c.owner==user["id"],jobs.c.idempotency_key==key)).mappings().first()
            if prior:
                if prior["request_hash"]!=digest: raise CFError("idempotency_conflict","Job payload changed",409)
                return dict(prior)
            count=c.execute(select(func.count()).select_from(jobs).where(jobs.c.owner==user["id"],jobs.c.state.in_(["queued","running"]))).scalar_one()
            if count>=50: raise CFError("job_limit","Too many unfinished jobs",429)
            jid=uid()
            c.execute(jobs.insert().values(id=jid,owner=user["id"],profile_id=profile_id,profile_digest=profile_digest(self.registry,p),release_id=release_id,spec=spec,request_hash=digest,idempotency_key=key,state="queued",attempt_count=0,created_at=now()))
            record(c,user["id"],"job_submitted",jid)
            return {"id":jid,"state":"queued"}
    def claim(self,node):
        from .inventory import memory_admission
        if not node.get("last_seen") or now()-node["last_seen"]>90: raise CFError("heartbeat_required","A fresh inventory heartbeat is required",409)
        if node["inventory"].get("on_battery") and not node["inventory"].get("policy",{}).get("allow_battery",False): return {"job":None,"reason":"on_battery"}
        eligible=[]
        for cap in node["capabilities"]:
            if cap["profile_id"] not in node["desired"]["profiles"]: continue
            ok,_=memory_admission(node["inventory"],cap,cap["backend"])
            if ok: eligible.append(cap)
        with self.db.transaction() as c:
            # One active compute job per node in this first extension, including unified RAM.
            c.execute(select(nodes).where(nodes.c.id==node["id"]).with_for_update()).first()
            active=c.execute(select(jobs).where(jobs.c.node_id==node["id"],jobs.c.state=="running",jobs.c.lease_until>now())).first()
            if active: return {"job":None,"reason":"compute_slot_occupied"}
            for cap in eligible:
                p=get_profile(self.registry,cap["profile_id"])
                condition=and_(jobs.c.profile_id==p["id"],jobs.c.profile_digest==cap["profile_digest"],jobs.c.release_id==cap.get("release_id"),jobs.c.attempt_count<3,or_(jobs.c.state=="queued",and_(jobs.c.state=="running",jobs.c.lease_until<now())))
                row=c.execute(select(jobs).where(condition).order_by(jobs.c.created_at).with_for_update(skip_locked=True).limit(1)).mappings().first()
                if row:
                    attempt=uid(); until=now()+120
                    c.execute(jobs.update().where(jobs.c.id==row["id"]).values(state="running",node_id=node["id"],attempt_id=attempt,lease_until=until,attempt_count=row["attempt_count"]+1))
                    return {"job":{**dict(row),"state":"running","node_id":node["id"],"attempt_id":attempt,"lease_until":until}}
            # Expired terminal retries must not leave permanent 'running' rows.
            c.execute(jobs.update().where(jobs.c.state=="running",jobs.c.lease_until<now(),jobs.c.attempt_count>=3).values(state="failed",error={"code":"retry_limit"}))
            return {"job":None,"reason":"no_compatible_ready_job"}
    def finish(self,node,jid,attempt,output=None,error=None,renew=False):
        with self.db.transaction() as c:
            row=c.execute(select(jobs).where(jobs.c.id==jid).with_for_update()).mappings().first()
            if not row or row["node_id"]!=node["id"] or row["attempt_id"]!=attempt: raise CFError("stale_attempt","Attempt does not own this job",409)
            if not renew and row["state"]=="done" and output==row["output"]: return {"id":jid,"state":"done","replayed":True}
            if row["state"]!="running" or row["lease_until"]<now(): raise CFError("stale_attempt","Lease expired or job is not running",409)
            if renew:
                until=now()+120;c.execute(jobs.update().where(jobs.c.id==jid).values(lease_until=until));return {"lease_until":until}
            state="failed" if error else "done"
            c.execute(jobs.update().where(jobs.c.id==jid).values(state=state,output=output,error=error))
            record(c,node["id"],"job_"+state,jid,{},row["owner"])
            return {"id":jid,"state":state}
