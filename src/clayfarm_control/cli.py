from __future__ import annotations
import argparse, getpass, json, os, platform, sys, time, uuid
from pathlib import Path
from . import __version__
from .common import CFError, atomic_json, read_json, secure_url, uid, canonical
from .registry import load_registry, plan, get_profile
from .inventory import probe
from .models import Models
from .client import Client
from .vault import Vault
from .device import new_key
from clayfarm.util import FarmError

def parser():
    p=argparse.ArgumentParser(prog="clayfarm",description="CLI-first control plane. Global --home/--json/--no-input/--yes may appear anywhere.")
    p.add_argument("--version",action="version",version=__version__)
    s=p.add_subparsers(dest="group",required=True)
    x=s.add_parser("setup");x.add_argument("--server",required=True);x.add_argument("--role",choices=["caller","worker","both"],default="caller");x.add_argument("--email");x.add_argument("--signup",action="store_true")
    a=s.add_parser("auth").add_subparsers(dest="action",required=True)
    for name in ("signup","login"):
        x=a.add_parser(name);x.add_argument("--email");x.add_argument("--send-only",action="store_true")
    x=a.add_parser("verify");x.add_argument("--email");x.add_argument("--code-stdin",action="store_true")
    a.add_parser("whoami");a.add_parser("logout")
    x=a.add_parser("mfa-enroll");x=a.add_parser("mfa-verify");x.add_argument("--factor",required=True);x.add_argument("--code-stdin",action="store_true")
    a=s.add_parser("access").add_subparsers(dest="action",required=True)
    x=a.add_parser("request");x.add_argument("--reason",default="Asset production");x.add_argument("--grant",choices=["creator-basic","experimental"],default="creator-basic");x.add_argument("--idempotency-key")
    a.add_parser("status")
    a=s.add_parser("node").add_subparsers(dest="action",required=True)
    x=a.add_parser("probe");x.add_argument("--deep",action="store_true");x.add_argument("--python")
    x=a.add_parser("register");x.add_argument("--name",default=platform.node());x.add_argument("--idempotency-key")
    for name in ("status","list","capabilities","reconcile","stop"):a.add_parser(name)
    x=a.add_parser("worker");x.add_argument("--once",action="store_true")
    x=a.add_parser("configure");x.add_argument("--runtime",type=Path,required=True)
    x=a.add_parser("selftest");x.add_argument("--blender")
    x=a.add_parser('warm');x.add_argument('--engine',choices=['sf3d','triposr'],required=True)
    x.add_argument('--repo');x.add_argument('--python');x.add_argument('--test-image',type=Path,required=True)
    x.add_argument('--install',action='store_true');x.add_argument('--ref');x.add_argument('--model-revision')
    x.add_argument('--accept-model-license',action='store_true')
    x=a.add_parser("policy");x.add_argument("--auto-install-builtin",action=argparse.BooleanOptionalAction,default=None);x.add_argument("--allow-battery",action=argparse.BooleanOptionalAction,default=None)
    x=a.add_parser("state");x.add_argument("node_id");x.add_argument("--status",choices=["active","paused","revoked"],required=True)
    a=s.add_parser("admin").add_subparsers(dest="action",required=True)
    x=a.add_parser("requests");x.add_argument("--state",choices=["pending","approved","rejected"],default="pending")
    for name in ("approve","reject"):
        x=a.add_parser(name);x.add_argument("request_id");x.add_argument("--grant",choices=["creator-basic","experimental","release-manager"])
    a.add_parser("users")
    x=a.add_parser("user-set");x.add_argument("user_id");x.add_argument("--status",choices=["active","suspended"]);x.add_argument("--grants",nargs="*")
    x=a.add_parser("desired");x.add_argument("node_id");x.add_argument("--profiles",nargs="*",required=True);x.add_argument("--experimental",action="store_true");x.add_argument("--expected-revision",type=int,required=True)
    x=a.add_parser("audit");x.add_argument("--after",type=int,default=0)
    x=a.add_parser("engines");x.add_argument("node_id");x.add_argument("--engines",nargs="*",choices=['sf3d','triposr','blender'],required=True)
    a=s.add_parser("catalog").add_subparsers(dest="action",required=True)
    x=a.add_parser("list");x.add_argument("--remote",action="store_true")
    x=a.add_parser("describe");x.add_argument("profile_id")
    a=s.add_parser("models").add_subparsers(dest="action",required=True)
    x=a.add_parser("plan");x.add_argument("--inventory",type=Path);x.add_argument("--kinds",default="3d_model,texture,vfx,ui,sfx,rigging,animation");x.add_argument("--experimental",action="store_true")
    a.add_parser("list")
    x=a.add_parser("sync");x.add_argument("--profile");x.add_argument("--recipe",type=Path);x.add_argument("--accept-license",action="store_true");x.add_argument("--allow-download",action="store_true")
    x=a.add_parser("verify");x.add_argument("profile_id");x.add_argument("--spec",type=Path)
    x=a.add_parser("generate");x.add_argument("profile_id");x.add_argument("--spec",type=Path,required=True);x.add_argument("--out",type=Path,required=True)
    a=s.add_parser("trust").add_subparsers(dest="action",required=True)
    x=a.add_parser("add");x.add_argument("--key-id",required=True);x.add_argument("--public-key-file",type=Path,required=True)
    a.add_parser("list")
    a=s.add_parser("releases").add_subparsers(dest="action",required=True)
    a.add_parser("list")
    x=a.add_parser("verify");x.add_argument("file",type=Path)
    x=a.add_parser("publish");x.add_argument("file",type=Path)
    a=s.add_parser("notify").add_subparsers(dest="action",required=True)
    for name in ("inbox","watch"):
        x=a.add_parser(name);x.add_argument("--after",type=int,default=0);x.add_argument("--timeout",type=int,default=0)
    a=s.add_parser("jobs").add_subparsers(dest="action",required=True)
    x=a.add_parser("submit");x.add_argument("--profile");x.add_argument("--spec",type=Path,required=True);x.add_argument("--release");x.add_argument("--idempotency-key")
    x.add_argument('--engine',choices=['sf3d','triposr']);x.add_argument('--concept',type=Path,action='append');x.add_argument('--job-id')
    x=a.add_parser('retry-submit');x.add_argument('job_id')
    a.add_parser("list")
    x=a.add_parser("get");x.add_argument("job_id");x.add_argument("--wait",type=int,default=0)
    x=a.add_parser("cancel");x.add_argument("job_id")
    x=a.add_parser('approve');x.add_argument('job_id');x.add_argument('--task',required=True)
    x=a.add_parser("result");x.add_argument("job_id");x.add_argument("--out",type=Path,required=True)
    a=s.add_parser("service").add_subparsers(dest="action",required=True)
    a.add_parser("plan");a.add_parser("install");a.add_parser("uninstall")
    a=s.add_parser("control").add_subparsers(dest="action",required=True)
    a.add_parser("init")
    x=a.add_parser("bootstrap");x.add_argument("--user-id",required=True);x.add_argument("--email",required=True)
    x=a.add_parser("serve");x.add_argument("--host",default="127.0.0.1");x.add_argument("--port",type=int,default=8765);x.add_argument('--development-queue',action='store_true')
    x=a.add_parser('bind-farm');x.add_argument('--farm-id',required=True)
    x=a.add_parser("notify-deliver");x.add_argument("--dry-run",action="store_true")
    x=s.add_parser("demo");x.add_argument("--out",type=Path,default=Path("clayfarm-v03-demo"))
    s.add_parser("doctor")
    x=s.add_parser("legacy");x.add_argument("args",nargs=argparse.REMAINDER)
    return p

def ask(prompt,args,secret=False):
    if args.no_input:raise CFError("input_required",prompt,428)
    return (getpass.getpass(prompt+": ") if secret else input(prompt+": ")).strip()

def confirm(message,args):
    if args.yes:return
    if args.no_input or input(message+" [y/N]: ").strip().lower()!="y":raise CFError("confirmation_required","Operation not executed",428)

def login(client,args,signup=False,send_only=False,email=None):
    email=email or getattr(args,"email",None) or ask("Email",args)
    client.auth().otp(email,signup)
    atomic_json(client.home/"pending-login.json",{"email":email})
    if send_only:return {"status":"code_sent","email":email,"next":"clayfarm auth verify"}
    code=ask("Email verification code",args,True)
    session=client.auth().verify(email,code)
    session["expires_at"]=session.get("expires_at",time.time()+session.get("expires_in",3600))
    client.vault.put("human-session",session)
    return {"status":"authenticated","user_id":session.get("user",{}).get("id")}

def register(client,args):
    key=client.vault.get("node-key")
    if not key:key=new_key();client.vault.put("node-key",key)
    pending=read_json(client.home/"node-request.json")
    if pending and getattr(args,"idempotency_key",None) not in (None,pending["idempotency_key"]): raise CFError("registration_in_progress","Existing registration intent exists")
    if not pending:
        pending={"kind":"node","payload":{"name":getattr(args,"name",None) or platform.node(),"public_key":key["public"],"inventory":probe()},"idempotency_key":getattr(args,"idempotency_key",None) or uid()}
        atomic_json(client.home/"node-request.json",pending)
    result=client.call("POST","/v1/requests",pending)
    client.config["node_id"]=result["id"];atomic_json(client.home/"control.json",client.config)
    return {"request_id":result["id"],"node_id":result["id"],"state":result["state"]}

def dispatch(a):
    home=a.home.expanduser().resolve();home.mkdir(parents=True,exist_ok=True)
    if os.name!="nt":os.chmod(home,0o700)
    registry=load_registry();g=a.group;act=getattr(a,"action",None)
    if g=="legacy":
        # Separate, explicit legacy namespace. No migration and no managed credentials injected.
        from clayfarm.cli import main as old_main
        old=sys.argv
        try:sys.argv=["assetgen",*a.args];return old_main()
        finally:sys.argv=old
    if g=="demo":
        from .demo import demo
        return demo(a.out)
    if g=="doctor":
        return {"python":sys.version,"inventory":probe(),"config_present":(home/"control.json").exists(),"legacy_home_untouched":True,"source_root":str(Path(__file__).resolve().parents[1])}
    if g=="node" and act=="probe":return probe(python=a.python,deep=a.deep)
    if g=="catalog" and not getattr(a,"remote",False):
        if act=="describe":return get_profile(registry,a.profile_id)
        from .registry import ADAPTERS
        return {"registry_revision":registry["registry_revision"],"profiles":[{"id":p["id"],"backend":p["backend"],"asset_kinds":p["asset_kinds"],"adapter_implemented":p["id"] in ADAPTERS,"node_ready":False} for p in registry["profiles"]]}
    if g=="models":
        m=Models(home,registry)
        if act=="plan":
            inv=read_json(a.inventory) if a.inventory else probe()
            result=plan(registry,inv,kinds=a.kinds.split(","),experimental=a.experimental,installed=m.states(),verified_profiles=[c['profile_id'] for c in m.capabilities()])
            result["inventory_source"]="provided_fixture_not_live_hardware" if a.inventory else "local_probe"
            return result
        if act=="list":return m.states()
        if act=="sync":
            if bool(a.profile)==bool(a.recipe):raise CFError("invalid_args","Specify exactly one of --profile or --recipe")
            confirm("Install the selected profile into the separate control home?",a)
            if a.profile:return m.builtin_sync(a.profile)
            return m.sync_recipe(read_json(a.recipe),read_json(home/"trust.json",{}),accept_license=a.accept_license,allow_download=a.allow_download)
        if act=="verify":return m.verify(a.profile_id,read_json(a.spec) if a.spec else None)
        if act=="generate":return m.generate(a.profile_id,read_json(a.spec),a.out)
    if g=="node" and act=="capabilities":return Models(home,registry).capabilities()
    if g=="node" and act=="policy":
        policy=read_json(home/"policy.json",{})
        for k in ("auto_install_builtin","allow_battery"):
            v=getattr(a,k)
            if v is not None:policy[k]=v
        atomic_json(home/"policy.json",policy);return policy
    if g=="node" and act=="stop":
        (home/"CONTROL_STOP").write_text("drain requested\n")
        if (home/'central-worker').is_dir(): (home/'central-worker'/'STOP').write_text('drain requested\n')
        return {"state":"stop_requested","effect":"After the current compute task returns; not forced termination"}
    if g=='node' and act=='configure':
        from .central_worker import RUNTIME_FIELDS
        value=read_json(a.runtime)
        if not isinstance(value,dict) or set(value)-RUNTIME_FIELDS: raise CFError('invalid_runtime_config','Provide executor settings only, without enrollment or credentials')
        atomic_json(home/'execution.json',value)
        return {'configured':True,'execution_ready':False}
    if g=='node' and act=='selftest':
        from clayfarm.cli import selftest_blender
        runtime=read_json(home/'execution.json',{})
        runtime.pop('blender_selftest',None)
        atomic_json(home/'execution.json',runtime)
        cfg={**runtime,'home':str(home/'central-worker')}
        if a.blender: cfg['blender']=a.blender
        from clayfarm.util import ProcessLock
        with ProcessLock(Path(cfg['home'])/'worker.lock'):
            result=selftest_blender(cfg)
        atomic_json(home/'execution.json',{**runtime,'blender':cfg.get('blender'),'blender_selftest':cfg.get('blender_selftest')})
        return result
    if g=='node' and act=='warm':
        from .central_worker import warm_engine
        return warm_engine(home,a)
    if g=="trust":
        trust=read_json(home/"trust.json",{})
        if act=="list":return trust
        from .device import public_key_valid
        from .common import sha
        key=public_key_valid(a.public_key_file.read_text().strip())
        if a.key_id in trust and trust[a.key_id]!=key:raise CFError("key_rotation_required","Cannot overwrite an existing trust root")
        confirm("Pin this release key after out-of-band fingerprint verification: "+sha(key.encode()),a)
        trust[a.key_id]=key;atomic_json(home/"trust.json",trust);return {"key_id":a.key_id,"fingerprint":sha(key.encode())}
    if g=="releases" and act=="verify":
        from .releases import verify_manifest
        return verify_manifest(read_json(a.file),read_json(home/"trust.json",{}))
    if g=="service":
        from .autostart import service
        if act!="plan":confirm("Modify current-user autostart? No privilege escalation will be attempted.",a)
        return service(home,act)
    if g=="control":
        from .db import Database
        db=Database(os.environ.get("CLAYFARM_DATABASE_URL","sqlite:///"+str(home/"control.db")))
        if act=="init":
            confirm("Initialize dedicated control metadata tables? Existing legacy tables are not touched.",a);db.init();return {"initialized":True,"legacy_migrated":False}
        if act=="bootstrap":
            confirm("Assign this verified Auth user as the first administrator?",a);return db.bootstrap_admin(a.user_id,a.email)
        if act=='bind-farm':
            from .bridge import CentralBridge
            bridge=CentralBridge(db,a.farm_id,None);bridge.bind_farm()
            return {'farm_id':bridge.farm_id,'bound':True,'new_farm_created':False}
        if act=="notify-deliver":
            from .notification import deliver
            return deliver(db,dry_run=a.dry_run)
        if act=="serve":
            from .auth import SupabaseAuth,SupabaseVerifier
            from .api import create_app
            import uvicorn
            if a.host not in ("127.0.0.1","::1","localhost") and os.environ.get("CLAYFARM_ALLOW_REMOTE")!="1":raise CFError("remote_bind_blocked","Configure HTTPS reverse proxy and explicitly set CLAYFARM_ALLOW_REMOTE=1")
            url=os.environ.get("SUPABASE_URL","");key=os.environ.get("SUPABASE_PUBLISHABLE_KEY","")
            auth=SupabaseAuth(url,key)
            bridge=None
            if not a.development_queue:
                from .bridge import CentralBridge,SupabaseStorage
                farm=os.environ.get('CLAYFARM_FARM_ID')
                if not farm: raise CFError('central_configuration_required','Set CLAYFARM_FARM_ID and the existing central database, or explicitly use --development-queue for isolated demos')
                bridge=CentralBridge(db,farm,SupabaseStorage(url,os.environ.get('SUPABASE_SERVICE_KEY','')))
            app=create_app(db,registry,SupabaseVerifier(auth),artifact_root=home/"artifacts",auth_config={"supabase_url":url,"publishable_key":key},release_trust=read_json(home/"trust.json",{}),bridge=bridge)
            uvicorn.run(app,host=a.host,port=a.port,access_log=False);return {"stopped":True}
    if g=="setup":
        server=secure_url(a.server,loopback=True)
        old=read_json(home/"control.json",{})
        if old.get("server") and old["server"]!=server:raise CFError("different_server","Use a different --home for a different control plane")
        atomic_json(home/"control.json",{**old,"server":server})
        c=Client(home);result={"login":login(c,a,signup=a.signup)}
        if a.role in ("caller","both"):
            result["access_request"]=c.call("POST","/v1/requests",{"kind":"access","payload":{"reason":"Initial setup","requested_grant":"creator-basic"},"idempotency_key":uid()})
        if a.role in ("worker","both"):result["node"]=register(c,a)
        return result
    c=Client(home)
    if g=="auth":
        if act in ("signup","login"):return login(c,a,signup=act=="signup",send_only=a.send_only)
        if act=="verify":
            email=a.email or read_json(home/"pending-login.json",{}).get("email") or ask("Email",a)
            code=sys.stdin.readline().strip() if a.code_stdin else ask("Email verification code",a,True)
            session=c.auth().verify(email,code);session["expires_at"]=session.get("expires_at",time.time()+session.get("expires_in",3600));c.vault.put("human-session",session)
            return {"status":"authenticated","user_id":session.get("user",{}).get("id")}
        if act=="whoami":return c.call("GET","/v1/me")
        if act=="logout":
            token=c.session()["access_token"]
            # Fail closed on server revocation; do not pretend offline logout revoked remote access.
            c.call("POST","/v1/sessions/revoke",{})
            c.auth().logout(token);c.vault.delete("human-session");return {"signed_out":True,"server_revoked":True}
        if act=="mfa-enroll":
            if a.no_input or a.json:raise CFError("interactive_secret_required","Enroll interactively; TOTP secrets are not emitted in JSON logs")
            factor=c.auth().factor_enroll(c.session()["access_token"])
            print("Authenticator setup secret (do not share): "+factor["totp"]["secret"],file=sys.stderr)
            return {"factor_id":factor["id"],"next":"clayfarm auth mfa-verify --factor "+factor["id"]}
        if act=="mfa-verify":
            code=sys.stdin.readline().strip() if a.code_stdin else ask("Authenticator code",a,True)
            session=c.auth().factor_verify(c.session()["access_token"],a.factor,code)
            if "access_token" not in session:raise CFError("mfa_session_missing","MFA did not return a session")
            session["expires_at"]=session.get("expires_at",time.time()+session.get("expires_in",3600));c.vault.put("human-session",session)
            return {"status":"mfa_verified"}
    if g=="access":
        if act=="status":return c.call("GET","/v1/requests")
        return c.call("POST","/v1/requests",{"kind":"access","payload":{"reason":a.reason,"requested_grant":a.grant},"idempotency_key":a.idempotency_key or uid()})
    if g=="node":
        if act=="register":return register(c,a)
        if act=="status":return c.call("GET","/v1/node/status",node=True)
        if act=="list":return c.call("GET","/v1/nodes")
        if act=="state":
            confirm("Change this node's state to "+a.status+"?",a);return c.call("PATCH",f"/v1/nodes/{a.node_id}/status",{"status":a.status})
        if act=='worker' and c.call('GET','/health',anonymous=True).get('queue_backend')=='public.cf_jobs/cf_tasks':
            from .central_worker import run
            return run(home,c,a.once)
        from .agent import Agent
        agent=Agent(home,c)
        if act=="reconcile":return agent.reconcile()
        if act=="worker":return agent.run(a.once)
    if g=="admin":
        if act=='engines': return c.call('PUT',f'/v1/admin/nodes/{a.node_id}/engines',{'engines':a.engines})
        if act=="requests":return c.call("GET","/v1/admin/requests?state="+a.state)
        if act in ("approve","reject"):
            confirm(f"{act} request {a.request_id}?",a)
            return c.call("POST",f"/v1/admin/requests/{a.request_id}/decision",{"approve":act=="approve","grant":a.grant})
        if act=="users":return c.call("GET","/v1/admin/users")
        if act=="user-set":
            confirm("Modify member access?",a);return c.call("PATCH",f"/v1/admin/users/{a.user_id}",{k:v for k,v in {"status":a.status,"grants":a.grants}.items() if v is not None})
        if act=="desired":
            confirm("Set node desired profiles? This does not override node-owner consent.",a)
            return c.call("PUT",f"/v1/admin/nodes/{a.node_id}/desired",{"profiles":a.profiles,"experimental":a.experimental,"expected_revision":a.expected_revision})
        if act=="audit":return c.call("GET",f"/v1/admin/audit?after={a.after}")
    if g=="catalog":return c.call("GET","/v1/catalog")
    if g=="releases":
        if act=="list":return c.call("GET","/v1/releases")
        confirm("Publish this signed immutable release?",a);return c.call("POST","/v1/admin/releases",read_json(a.file))
    if g=="notify":
        after=a.after;end=time.monotonic()+a.timeout if a.timeout else None
        while True:
            items=c.call("GET",f"/v1/notifications?after={after}")
            if act=="inbox":return items
            for item in items:print(json.dumps(item,ensure_ascii=False),flush=True);after=item["id"]
            if end and time.monotonic()>=end:return {"status":"watch_timeout","last_event":after}
            time.sleep(3)
    if g=="jobs":
        central=c.call('GET','/health',anonymous=True).get('queue_backend')=='public.cf_jobs/cf_tasks'
        if central:
            from .bridge_client import BridgeBackend
            from clayfarm.cli import submit_job,retry_submit,collect_result
            backend=BridgeBackend(c)
            if act=='submit':
                if not a.engine or not a.concept or a.profile: raise CFError('central_queue_required','Use --engine sf3d|triposr and --concept with a 3D --spec')
                jid=a.job_id or a.idempotency_key or uid()
                return submit_job(backend,home/'central-caller',read_json(a.spec),a.concept,[a.engine],{'agent':'clayfarm-cli'},job_id=jid)
            if act=='retry-submit': return retry_submit(backend,home/'central-caller',a.job_id)
            if act=='list': return backend.rpc('list')
            if act=='approve': return backend.rpc('approve',{'id':a.job_id,'task_id':a.task})
            if act=='get':
                deadline=time.monotonic()+max(0,a.wait)
                while True:
                    view=backend.rpc('get',{'id':a.job_id})
                    if all(t['status'] in ('done','failed','cancelled') for t in view['tasks']) or time.monotonic()>=deadline:return view
                    time.sleep(2)
            if act=='cancel': return backend.rpc('cancel',{'id':a.job_id})
            if act=='result': return collect_result(backend,a.job_id,a.out,artifacts=True)
        if act=='submit' and (not a.profile or a.engine): raise CFError('profile_required','Development queue requires --profile; central 3D needs a configured central server')
        if act=="submit":return c.call("POST","/v1/jobs",{"profile_id":a.profile,"spec":read_json(a.spec),"release_id":a.release,"idempotency_key":a.idempotency_key or uid()})
        if act=="list":return c.call("GET","/v1/jobs")
        if act=="get":
            deadline=time.monotonic()+max(0,a.wait)
            while True:
                job=c.call("GET",f"/v1/jobs/{a.job_id}")
                if job["state"] in ("done","failed","cancelled") or time.monotonic()>=deadline:return job
                time.sleep(2)
        if act=="cancel":return c.call("POST",f"/v1/jobs/{a.job_id}/cancel",{})
        if act=="result":
            job=c.call("GET",f"/v1/jobs/{a.job_id}")
            data=c.call("GET",f"/v1/jobs/{a.job_id}/artifact",download=True)
            from .common import sha
            if sha(data)!=job["output"]["sha256"]:raise CFError("artifact_hash_mismatch","Downloaded artifact failed verification")
            if a.out.exists():raise CFError("output_exists","Refusing to overwrite an existing output")
            a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(data)
            return {"file":str(a.out.resolve()),"sha256":sha(data)}
    raise CFError("unknown_command","Command is not implemented")

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    global_parser=argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--home",type=Path,default=Path.home()/".clayfarm-control")
    global_parser.add_argument("--json",action="store_true");global_parser.add_argument("--no-input",action="store_true");global_parser.add_argument("--yes",action="store_true")
    global_args,rest=global_parser.parse_known_args(argv)
    a=parser().parse_args(rest)
    for k,v in vars(global_args).items():setattr(a,k,v)
    try:
        result=dispatch(a)
        if result is not None:print(json.dumps(result,ensure_ascii=False,indent=None if a.json else 2,allow_nan=False))
        return 0
    except CFError as e:
        print(json.dumps({"error":{"code":e.code,"message":e.message}},ensure_ascii=False),file=sys.stderr)
        return 4 if e.status in (401,403) else 5 if e.status==409 else 6 if e.status==503 else 2
    except KeyboardInterrupt:return 130
    except FarmError:
        print(json.dumps({'error':{'code':'executor_failed','message':'3D executor operation failed; inspect its local diagnostic log'}}),file=sys.stderr);return 2
    except (OSError,ValueError,KeyError) as e:
        print(json.dumps({"error":{"code":"local_error","message":str(e)[:300]}}),file=sys.stderr);return 2
