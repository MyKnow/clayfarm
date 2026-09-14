from __future__ import annotations
import json, os, platform, shutil, subprocess, sys, time, uuid, venv
from pathlib import Path
from .common import CFError, atomic_json, read_json, file_sha, canonical, sha, safe_id, safe_relative
from .registry import get_profile, profile_digest, ADAPTERS
from .releases import verify_manifest
from clayfarm.util import ProcessLock
from . import __version__

class Models:
    def __init__(self,home,registry):
        self.home=Path(home);self.registry=registry;self.root=self.home/"models";self.root.mkdir(parents=True,exist_ok=True)
    def states(self):
        result={}
        for p in self.root.glob("*/current.json"):
            x=read_json(p,{})
            if x: result[p.parent.name]=x
        return result
    def adapter_digest(self,pid):
        base=Path(__file__).parent
        paths=[base/"runtime.py",base/"models.py",base/"adapters/builtin.py",base/"adapters/diffusers_image.py",base/"adapters/stable_audio.py",base/"audio.py",base/"sound_direction.py",base/"process.py",base/"inventory.py",base/"registry.py"]
        return sha(b"".join(p.read_bytes() for p in paths)+pid.encode())
    def environment_fingerprint(self,python):
        script="import importlib.metadata as m,json,sys; print(json.dumps({'python':sys.version,'packages':sorted((d.metadata['Name'],d.version) for d in m.distributions() if d.metadata.get('Name'))},sort_keys=True))"
        try:
            result=subprocess.run([python,"-c",script],capture_output=True,text=True,timeout=30,check=True)
            return sha(result.stdout.strip().encode())
        except (OSError,subprocess.SubprocessError) as e:raise CFError("environment_unavailable","Cannot inspect the selected Python environment") from e
    def builtin_sync(self,pid):
        p=get_profile(self.registry,pid)
        if ADAPTERS.get(pid) not in ("builtin_ui","builtin_sfx"): raise CFError("signed_recipe_required","A signed, pinned model recipe is required")
        with ProcessLock(self.home/"models.lock"):
            old=read_json(self.root/pid/"current.json",{})
            envfp=self.environment_fingerprint(sys.executable)
            if old and old.get("profile_digest")==profile_digest(self.registry,p) and old.get("adapter_digest")==self.adapter_digest(pid) and old.get("environment_fingerprint")==envfp: return old
            state={"profile_id":pid,"profile_digest":profile_digest(self.registry,p),"status":"installed_unverified","backend":"cpu","python":sys.executable,"adapter_digest":self.adapter_digest(pid),"model_dir":None,"release_id":f"bundled-{__version__}","environment_fingerprint":envfp}
            if old: atomic_json(self.root/pid/"previous.json",old)
            atomic_json(self.root/pid/"current.json",state)
            return state
    def sync_recipe(self,envelope,trust,*,accept_license=False,allow_download=False):
        pid=envelope.get("signed",{}).get("profile_id",""); safe_id(pid)
        p=get_profile(self.registry,pid)
        if not accept_license or not allow_download: raise CFError("consent_required","Explicit license and download approval are required")
        with ProcessLock(self.home/"models.lock"):
            ledger=read_json(self.root/pid/"release-ledger.json",{})
            m=verify_manifest(envelope,trust,highwater=ledger.get("sequence",0))
            if m["kind"]!="model_profile" or m["profile_digest"]!=profile_digest(self.registry,p) or m["backend"]!=p["backend"] or m["adapter"]!=ADAPTERS.get(pid): raise CFError("recipe_mismatch","Recipe does not match local profile/adapter")
            if m["sequence"]==ledger.get("sequence") and ledger.get("digest")!=sha(canonical(m)): raise CFError("release_equivocation","Same sequence has different content")
            if m.get("platform")!={"os":{"Darwin":"macos","Windows":"windows"}.get(platform.system(),platform.system().lower()),"arch":platform.machine()}:
                raise CFError("platform_mismatch","Recipe environment is for another OS/architecture")
            expected_model=self.registry["models"][p["model_id"]]["repository"]
            if m["model"]["repository"]!=expected_model: raise CFError("recipe_mismatch","Model repository differs from registry")
            atomic_json(self.root/pid/"release-ledger.json",{"sequence":m["sequence"],"digest":sha(canonical(m))})
            stage=self.root/pid/"releases"/safe_id(m["id"]);stage.mkdir(parents=True,exist_ok=True)
            atomic_json(stage/"release.json",envelope)
            # A complete pip --require-hashes lock and isolated venv; never mutate running envs.
            python_minor=".".join(platform.python_version_tuple()[:2])
            if python_minor!=m["environment"]["python_minor"]: raise CFError("python_mismatch","Install the exact Python minor requested by the release first")
            envdir=stage/"venv";exe=envdir/("Scripts/python.exe" if os.name=="nt" else "bin/python")
            if not exe.exists(): venv.EnvBuilder(with_pip=True).create(envdir)
            lock=stage/"requirements.lock";lock.write_text(m["environment"]["requirements"])
            env={k:v for k,v in os.environ.items() if not k.startswith(("PIP_","SUPABASE_","CLAYFARM_"))}
            env.update({"PIP_CONFIG_FILE":os.devnull,"PIP_DISABLE_PIP_VERSION_CHECK":"1"})
            with (stage/"install.log").open("ab") as log:
                done=subprocess.run([str(exe),"-m","pip","install","--require-hashes","--only-binary=:all:","--index-url","https://pypi.org/simple","-r",str(lock)],stdout=log,stderr=log,env=env,timeout=3600)
            if done.returncode: raise CFError("environment_install_failed","See local install.log; existing active environment preserved")
            try: from huggingface_hub import snapshot_download
            except ImportError as e: raise CFError("dependency_missing","Install the models optional dependency first") from e
            weights=stage/"weights"
            snapshot_download(repo_id=m["model"]["repository"],revision=m["model"]["revision"],allow_patterns=list(m["model"]["files"]),local_dir=str(weights))
            for name,digest in m["model"]["files"].items():
                file=safe_relative(weights,name)
                if not file.is_file() or file_sha(file)!=digest: raise CFError("model_hash_mismatch","Downloaded model failed file verification")
            # Do NOT activate before runtime verification; keep candidate in pending.json.
            state={"profile_id":pid,"profile_digest":m["profile_digest"],"status":"installed_unverified","backend":p["backend"],"python":str(exe.resolve()),"model_dir":str(weights.resolve()),"adapter_digest":self.adapter_digest(pid),"release_id":m["id"],"release_sequence":m["sequence"],"model_revision":m["model"]["revision"],"model_files":m["model"]["files"],"environment_lock_sha256":m["environment"]["sha256"],"environment_fingerprint":self.environment_fingerprint(str(exe))}
            atomic_json(self.root/pid/"pending.json",state)
            return state
    def _run(self,pid,spec,out,state,cancel=None):
        p=get_profile(self.registry,pid)
        if state.get("profile_digest")!=profile_digest(self.registry,p) or state.get("adapter_digest")!=self.adapter_digest(pid): raise CFError("stale_verification","Profile or adapter changed; resync and reverify")
        if state.get("environment_fingerprint")!=self.environment_fingerprint(state["python"]): raise CFError("environment_changed","Runtime dependencies changed; resync and reverify")
        if state.get("model_files"):
            for name,digest in state["model_files"].items():
                file=safe_relative(Path(state["model_dir"]),name)
                if not file.is_file() or file_sha(file)!=digest: raise CFError("model_hash_mismatch","Installed model changed")
        out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
        request=out/"request.json";result=out/"receipt.json";result.unlink(missing_ok=True)
        atomic_json(request,{"profile":p,"spec":spec,"model_dir":state.get("model_dir") or ".","out":str(out),"runtime_python":state.get("python")})
        allow={"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","TMPDIR","HOME","USERPROFILE","LOCALAPPDATA","APPDATA","LD_LIBRARY_PATH","DYLD_LIBRARY_PATH","CUDA_HOME","CUDA_PATH","LANG","LC_ALL"}
        env={k:v for k,v in os.environ.items() if k in allow}
        env.update({"PYTHONPATH":str(Path(__file__).resolve().parents[1]),"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1","PYTORCH_ENABLE_MPS_FALLBACK":"0"})
        from .inventory import probe, memory_admission, GIB
        inventory=probe(python=state['python'],deep=p['backend']!='cpu')
        if state.get('status')=='verified':
            allowed,reason=memory_admission(inventory,state,p['backend'])
            if not allowed: raise CFError('memory_admission_failed',reason,409)
        if p['backend']=='mps':
            # Unified RAM is shared with the user's other applications. Reserve
            # 2 GiB for the host and 1 GiB for the Python/CPU side of initial runs.
            budget=inventory['ram_available_bytes']-3*GIB
            if budget<=0: raise CFError('memory_pressure','Insufficient unified memory for initial verification',409)
            request_data=read_json(request);request_data['device_budget_bytes']=budget
            atomic_json(request,request_data)
        if p["backend"]=="cuda":
            devices=inventory.get("devices",[])
            if not devices:raise CFError("backend_unavailable","No NVIDIA device detected")
            env["CUDA_VISIBLE_DEVICES"]=devices[0]["id"]
            budget=devices[0]['free_bytes']-512*1024**2
            if budget<=0:raise CFError('memory_pressure','Insufficient CUDA memory for bounded verification',409)
            request_data=read_json(request);request_data['device_budget_bytes']=budget
            atomic_json(request,request_data)
        # Only built-in entry points; no arbitrary command comes from a job or registry.
        from .process import run_isolated
        try: run_isolated([state["python"],"-m","clayfarm_control.runtime",str(request),str(result)],out,out/"runtime.log",1800,env,cancel,memory_reserve_bytes=2*GIB)
        except Exception as e:
            reason=read_json(result,{})
            raise CFError(reason.get("code",getattr(e,'code','runtime_failed')),reason.get("message",getattr(e,'message','Runtime failed; inspect local runtime.log'))) from e
        evidence=read_json(result,{})
        if evidence.get("status")!="verified": raise CFError("verification_failed","No successful runtime receipt")
        if evidence.get('backend')!=p['backend'] or not evidence.get('peak_host_bytes'):
            raise CFError('verification_failed','Runtime backend and memory evidence are required')
        if p.get('model_id') and evidence.get('details',{}).get('neural') is not True:
            raise CFError('verification_failed','Real neural execution evidence is required')
        if p.get('model_id') and p['backend']!="cpu" and not evidence.get('peak_device_bytes'):
            raise CFError('verification_failed','Device memory evidence is required for non-CPU neural execution')
        artifact=Path(evidence["artifact"]).resolve()
        if not artifact.is_relative_to(out) or not artifact.is_file() or file_sha(artifact)!=evidence["artifact_sha256"]: raise CFError("invalid_artifact","Output artifact failed validation")
        return {**evidence,"profile_id":pid,"profile_digest":state["profile_digest"],"adapter_digest":state["adapter_digest"],"release_id":state["release_id"]}
    def verify(self,pid,spec=None):
        safe_id(pid)
        with ProcessLock(self.home/"models.lock"):
            state=read_json(self.root/pid/"pending.json") or read_json(self.root/pid/"current.json")
            if not state: raise CFError("model_not_installed","Sync this profile first")
            if spec is None:
                if pid=="deterministic-ui": spec={"text":"ClayFarm 검증"}
                elif pid=="procedural-sfx": spec={"effect":"beep","seconds":.2}
                elif pid.startswith("sa3-small-music"):
                    spec={"track_id":"lobby","prompt":"bright open welcoming instrumental melody for a game lobby","duration_seconds":5,"loop_required":True,"seed":0}
                elif pid.startswith("sa3-small"):
                    spec={"event_id":"verification","prompt":"short neutral game sound effect","duration_seconds":.2,"variation_count":1,"seed":0}
                else: spec={"prompt":"one matte clay cube on a plain neutral background","seed":0}
            out=self.root/pid/"verification"/str(uuid.uuid4())
            evidence=self._run(pid,spec,out,state)
            current=read_json(self.root/pid/"current.json")
            if current: atomic_json(self.root/pid/"previous.json",current)
            active={**state,**evidence,"status":"verified"}
            atomic_json(self.root/pid/"current.json",active)
            (self.root/pid/"pending.json").unlink(missing_ok=True)
            return active
    def generate(self,pid,spec,out,cancel=None):
        with ProcessLock(self.home/"models.lock"):
            state=read_json(self.root/safe_id(pid)/"current.json",{})
            if state.get("status")!="verified": raise CFError("model_not_verified","Run models verify first")
            return self._run(pid,spec,out,state,cancel)
    def capabilities(self):
        caps=[]
        for pid,s in self.states().items():
            try:
                p=get_profile(self.registry,pid)
                if pid not in ADAPTERS or s.get("status")!="verified" or s.get("backend")!=p["backend"]: continue
                if s.get("adapter_digest")!=self.adapter_digest(pid) or s.get("profile_digest")!=profile_digest(self.registry,p): continue
                if s.get("environment_fingerprint")!=self.environment_fingerprint(s["python"]): continue
                if not isinstance(s.get("peak_host_bytes"),int) or s["peak_host_bytes"]<=0: continue
                if p["backend"]!="cpu" and (not isinstance(s.get("peak_device_bytes"),int) or s["peak_device_bytes"]<=0): continue
                artifact=Path(s["artifact"])
                if not artifact.is_file() or file_sha(artifact)!=s.get("artifact_sha256"): continue
                if any(not safe_relative(Path(s["model_dir"]),name).is_file()
                       or file_sha(safe_relative(Path(s["model_dir"]),name))!=digest
                       for name,digest in s.get("model_files",{}).items()): continue
                keys=("profile_id","profile_digest","status","backend","tested_at","peak_host_bytes","peak_device_bytes","artifact_sha256","adapter_digest","release_id","duration_seconds")
                caps.append({k:s.get(k) for k in keys})
            except (CFError,OSError,KeyError,TypeError,ValueError):
                continue
        return caps
