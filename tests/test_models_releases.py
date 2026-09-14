import copy,time,json,struct,wave,sys,subprocess,os
from pathlib import Path
import pytest
from clayfarm_control.common import CFError,sha,canonical
from clayfarm_control.registry import load_registry,get_profile,profile_digest
from clayfarm_control.models import Models
from clayfarm_control.releases import sign_manifest,verify_manifest,validate_requirements
from clayfarm_control.device import new_key
from clayfarm_control.adapters.builtin import generate,validate_spec

def manifest():
    reg=load_registry();p=get_profile(reg,"sd-turbo-cuda");lock="psutil==7.2.2 --hash=sha256:"+"a"*64+"\n"
    return {"schema_version":1,"id":"sd-turbo-release-1","kind":"model_profile","sequence":1,"issued_at":time.time()-1,"expires_at":time.time()+3600,"profile_id":p["id"],"profile_digest":profile_digest(reg,p),"adapter":"diffusers_image","backend":"cuda","platform":{"os":"windows","arch":"AMD64"},"model":{"repository":"stabilityai/sd-turbo","revision":"a"*40,"files":{"model.safetensors":"b"*64}},"environment":{"python_minor":"3.11","requirements":lock,"sha256":sha(lock.encode())},"license_id":"reviewed-test-license"}

def test_signed_manifest():
    k=new_key();m=manifest();assert verify_manifest(sign_manifest(m,k["private"],"release"),{"release":k["public"]})==m

@pytest.mark.parametrize("bad", [{"signed":{},"signatures":"bad"},{"signed":{"id":1},"signatures":[]}])
def test_malformed_release_envelope_is_structured_error(bad):
    with pytest.raises(CFError): verify_manifest(bad,{})

@pytest.mark.parametrize("mode",["tamper","expired","untrusted","rollback","floating","pickle","path"])
def test_bad_release_rejected(mode):
    k=new_key();m=manifest();high=0
    if mode=="expired":m["expires_at"]=time.time()-10
    if mode=="floating":m["model"]["revision"]="main"
    if mode=="pickle":m["model"]["files"]={"weights.pkl":"a"*64}
    if mode=="path":m["model"]["files"]={"../escape.json":"a"*64}
    envelope=sign_manifest(m,k["private"],"key")
    if mode=="tamper":envelope["signed"]["backend"]="mps"
    if mode=="rollback":high=2
    with pytest.raises(CFError):verify_manifest(envelope,{} if mode=="untrusted" else {"key":k["public"]},highwater=high)

@pytest.mark.parametrize("text",["torch>=2\n","--index-url https://bad.invalid\n","-e .\n","thing @ https://bad.invalid/thing.whl\n","foo==1.0\n"])
def test_unlocked_requirements_rejected(text):
    with pytest.raises(CFError):validate_requirements(text)

def test_sfx_actual_wave(tmp_path):
    path,details=generate("procedural-sfx",{"effect":"impact","seconds":.1},tmp_path)
    with wave.open(str(path)) as f:assert f.getnframes()==4800;assert f.getframerate()==48000
    assert details["neural"] is False

def test_svg_escapes_untrusted_text(tmp_path):
    path,_=generate("deterministic-ui",{"text":"<script>alert(1)</script>"},tmp_path)
    assert "<script>" not in path.read_text();assert "&lt;script&gt;" in path.read_text()

@pytest.mark.parametrize("spec",[{"seconds":float("nan")},{"seconds":-1},{"effect":"run_shell"},{"command":"rm -rf"}])
def test_bad_asset_spec_rejected(spec):
    with pytest.raises(CFError):validate_spec("procedural-sfx",spec)

@pytest.mark.parametrize("effect",["beep","whoosh","impact","sword_swing"])
def test_sfx_effects_accepted(effect):
    assert validate_spec("procedural-sfx",{"effect":effect})["effect"]==effect

@pytest.mark.parametrize("spec",[{"effect":"sword-swing"},{"effect":"SWORD_SWING"},{"effect":"katana_slash"},{"effect":"sword_swing","seconds":0},{"effect":"sword_swing","seconds":5.1},{"effect":"sword_swing","frequency":16001},{"effect":"sword_swing","frequency":39},{"effect":"sword_swing","seed":-1},{"effect":"sword_swing","gain":2}])
def test_sword_swing_spec_bounds_enforced(spec):
    with pytest.raises(CFError):validate_spec("procedural-sfx",spec)

def sword_frames(tmp_path,name,**overrides):
    spec={"effect":"sword_swing","seconds":.35,"frequency":1400,"seed":7,**overrides}
    path,details=generate("procedural-sfx",spec,tmp_path/name)
    with wave.open(str(path)) as f:
        assert f.getnchannels()==1 and f.getsampwidth()==2 and f.getframerate()==48000
        frames=f.readframes(f.getnframes())
    return list(struct.unpack("<%dh"%(len(frames)//2),frames)),details

def test_sword_swing_is_deterministic_pcm_wav(tmp_path):
    first,details=sword_frames(tmp_path,"a")
    again,_=sword_frames(tmp_path,"b")
    other,_=sword_frames(tmp_path,"c",seed=8)
    assert first==again and first!=other
    assert len(first)==16800 and details["sample_rate"]==48000 and details["channels"]==1
    assert details["kind"]=="sfx" and details["neural"] is False

def test_sword_swing_has_audible_attack_and_decay(tmp_path):
    samples,_=sword_frames(tmp_path,"swing")
    rms=lambda seg:(sum(v*v for v in seg)/len(seg))**.5
    quarter=len(samples)//4
    peak=max(abs(v) for v in samples)
    assert 3000<peak<=int(.8*32767)  # audible, still inside the adapter's clip guard
    assert samples[0]==0 and abs(samples[-1])<peak//8  # click-free start and tail
    assert max(range(len(samples)),key=lambda i:abs(samples[i]))<quarter  # short attack: loudest point is early
    assert rms(samples[:quarter])>4*rms(samples[-quarter:])  # decaying whoosh body

def test_cpu_sync_verify_generate(tmp_path):
    m=Models(tmp_path,load_registry());state=m.builtin_sync("procedural-sfx")
    assert state["status"]=="installed_unverified"
    assert m.capabilities()==[]
    verified=m.verify("procedural-sfx")
    assert verified["status"]=="verified" and verified["peak_host_bytes"]>0
    assert m.capabilities()[0]["backend"]=="cpu"
    result=m.generate("procedural-sfx",{"effect":"beep"},tmp_path/"result")
    assert Path(result["artifact"]).is_file()

def test_gpu_sync_without_recipe_refused(tmp_path):
    m=Models(tmp_path,load_registry())
    with pytest.raises(CFError):m.builtin_sync("sd-turbo-mps")

def cli_env():
    return {**os.environ,"PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src")}

def test_cli_json_output(tmp_path):
    r=subprocess.run([sys.executable,"-m","clayfarm_control","--home",str(tmp_path),"catalog","list","--json"],capture_output=True,text=True,env=cli_env())
    assert r.returncode==0;assert len(json.loads(r.stdout)["profiles"])==42

def test_cli_noninteractive_mutation_does_not_wait(tmp_path):
    r=subprocess.run([sys.executable,"-m","clayfarm_control","--home",str(tmp_path),"models","sync","--profile","procedural-sfx","--no-input"],capture_output=True,text=True,timeout=10,env=cli_env())
    assert r.returncode==2;assert json.loads(r.stderr)["error"]["code"]=="confirmation_required"


def test_changed_environment_is_not_advertised(tmp_path,monkeypatch):
    m=Models(tmp_path,load_registry());m.builtin_sync("procedural-sfx");m.verify("procedural-sfx")
    monkeypatch.setattr(m,"environment_fingerprint",lambda python:"changed")
    assert m.capabilities()==[]


def test_missing_receipt_is_not_advertised(tmp_path):
    from clayfarm_control.common import atomic_json,read_json
    m=Models(tmp_path,load_registry());m.builtin_sync("procedural-sfx");s=m.verify("procedural-sfx")
    Path(s["artifact"]).unlink()
    assert m.capabilities()==[]


def test_failed_blender_retest_clears_ready(tmp_path,monkeypatch):
    from clayfarm_control.common import atomic_json,read_json
    from clayfarm_control.cli import main
    from clayfarm.util import FarmError
    import clayfarm.cli
    atomic_json(tmp_path/"execution.json",{"blender":"old","blender_selftest":{"status":"passed"}})
    def fail(cfg):raise FarmError("Blender selftest failed")
    monkeypatch.setattr(clayfarm.cli,"selftest_blender",fail)
    assert main(["--home",str(tmp_path),"node","selftest"])==2
    assert not read_json(tmp_path/"execution.json").get("blender_selftest")

def test_manual_engine_ready_flag_has_no_execution_evidence(tmp_path):
    from clayfarm_control.central_worker import engine_verified
    assert not engine_verified({'home':str(tmp_path),'engines':{'triposr':{'ready':True,'offline_ready':True}}},'triposr')


def test_cli_warm_requires_pinned_install_revisions(tmp_path,capsys):
    from clayfarm_control.cli import main
    assert main(['--home',str(tmp_path),'node','warm','--engine','triposr','--test-image','test.png','--install'])==2
    assert json.loads(capsys.readouterr().err)['error']['code']=='pinned_revision_required'


def test_warm_does_not_reuse_online_output_as_offline_success(tmp_path,monkeypatch):
    import clayfarm.setup as setup
    import clayfarm.executors as executors
    from clayfarm.util import FarmError
    from clayfarm_control.common import atomic_json
    repo=tmp_path/"repo";repo.mkdir();(repo/"run.py").write_text("# fixture")
    python=tmp_path/"python";python.write_text("# fixture")
    concept=tmp_path/"test.png";concept.write_bytes(b"fixture")
    monkeypatch.setattr(setup,"gpu_stats",lambda:{"free_mb":8000})
    monkeypatch.setattr(setup,"probe",lambda argv:"a"*40)
    def fake_run(argv,cwd,log,*args):
        if str(argv[1]).endswith("resolve_model.py"):
            atomic_json(Path(argv[-1]),{"path":str(tmp_path/("b"*40))})
        elif str(argv[1]).endswith("run.py") and Path(argv[argv.index("--output-dir")+1]).name=="online":
            target=Path(argv[argv.index("--output-dir")+1])/"0";target.mkdir(parents=True)
            (target/"mesh.glb").write_bytes(b"glTF fixture only")
        # Offline process exits successfully without generating anything.
    monkeypatch.setattr(executors,"run",fake_run)
    cfg={"home":str(tmp_path/"worker")}
    with pytest.raises(FarmError,match="fresh GLB"):
        setup.warm(cfg,"triposr",repo,python,concept)
    assert cfg["engines"]["triposr"]["ready"] is False

def test_legacy_executor_does_not_inherit_new_gateway_credentials(tmp_path,monkeypatch):
    import threading
    from clayfarm.executors import run
    for key in ('SUPABASE_SERVICE_KEY','CLAYFARM_DATABASE_URL','CLAYFARM_TEST_SECRET'):
        monkeypatch.setenv(key,'fixture-only-sensitive-value')
    target=tmp_path/'env.json'
    script="import os,json,sys; open(sys.argv[1],'w').write(json.dumps([k for k in os.environ if k.startswith(('SUPABASE_','CLAYFARM_'))]))"
    run([sys.executable,'-c',script,str(target)],tmp_path,tmp_path/'log.txt',10,threading.Event())
    assert json.loads(target.read_text())==[]
