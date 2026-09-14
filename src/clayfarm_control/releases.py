"""Small signed-manifest verifier. NOT a complete TUF client (see SECURITY.md)."""
from __future__ import annotations
import base64, re, time
from pathlib import PurePosixPath
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from .common import CFError, canonical, safe_id, sha

def sign_manifest(manifest,private_key,key_id):
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key,validate=True))
    return {"signed":manifest,"signatures":[{"key_id":key_id,"signature":base64.b64encode(key.sign(canonical(manifest))).decode()}]}

def verify_manifest(envelope,trust,*,highwater=0,clock=None):
    if not isinstance(envelope,dict) or set(envelope)!={"signed","signatures"}: raise CFError("release_invalid","Invalid signed envelope")
    if not isinstance(envelope["signatures"],list) or not envelope["signatures"] or len(envelope["signatures"])>16: raise CFError("release_invalid","Invalid release signatures")
    if not isinstance(trust,dict): raise CFError("untrusted_release","A locally pinned release key is required")
    m=envelope["signed"]
    if not isinstance(m,dict): raise CFError("release_invalid","Manifest must be an object")
    allowed={"schema_version","id","kind","sequence","issued_at","expires_at","profile_id","profile_digest","adapter","backend","model","environment","license_id","platform","artifact","product","version","channel","release_notes"}
    if set(m)-allowed: raise CFError("release_invalid","Unknown manifest fields")
    if m.get("schema_version")!=1 or m.get("kind") not in ("model_profile","worker_bundle","control_release"): raise CFError("release_invalid","Unsupported release schema/kind")
    if not isinstance(m.get("id"),str): raise CFError("release_invalid","Release ID is required")
    safe_id(m["id"])
    if not isinstance(m.get("sequence"),int) or m["sequence"]<=0: raise CFError("release_invalid","A positive sequence is required")
    if m["sequence"]<highwater: raise CFError("rollback_attack","Release sequence is older than the locally observed version")
    clock=clock or time.time()
    try:
        if m["issued_at"]>clock+60 or m["expires_at"]<=clock or m["expires_at"]<=m["issued_at"]: raise ValueError()
    except (KeyError,TypeError,ValueError): raise CFError("release_expired","Expired or future-dated release")
    valid=False
    for signature in envelope["signatures"]:
        if not isinstance(signature,dict): continue
        key=trust.get(signature.get("key_id"))
        if not key: continue
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key,validate=True)).verify(base64.b64decode(signature["signature"],validate=True),canonical(m)); valid=True
        except Exception: continue
    if not valid: raise CFError("untrusted_release","A signature from a locally pinned release key is required")
    if m["kind"]=="control_release":
        _validate_control_release(m)
        return m
    if m["kind"]=="model_profile":
        if not re.fullmatch(r"[0-9a-f]{64}",m.get("profile_digest","")): raise CFError("release_invalid","Pinned profile digest required")
        model=m.get("model",{})
        if set(model)-{"repository","revision","files"}: raise CFError("release_invalid","Unknown model fields")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",model.get("repository","")) or not re.fullmatch(r"[0-9a-f]{40}",model.get("revision","")):
            raise CFError("unpinned_model","Model repository and full 40-character commit are required")
        if not isinstance(model.get("files"),dict) or not model["files"]: raise CFError("model_hashes_missing","Every installed model file requires a SHA-256")
        for path,digest in model["files"].items():
            from pathlib import PurePosixPath
            p=PurePosixPath(path)
            if p.is_absolute() or ".." in p.parts or "\\" in path or ":" in path or p.suffix in (".py",".pt",".pth",".bin",".ckpt",".pkl",".pickle") or not re.fullmatch(r"[0-9a-f]{64}",digest):
                raise CFError("unsafe_model_file","Unsafe path, executable/pickle weight, or invalid file hash")
        env=m.get("environment",{})
        if set(env)-{"python_minor","requirements","sha256"} or env.get("python_minor") not in ("3.11","3.12","3.13") or sha(env.get("requirements","").encode())!=env.get("sha256"):
            raise CFError("environment_unpinned","Pinned and hashed environment lock required")
        validate_requirements(env["requirements"])
        if not m.get("license_id"): raise CFError("license_required","Model license identifier required")
    return m

def _validate_control_release(m):
    """Validate a signed, transportable control-plane package manifest."""
    if m.get("product")!="clayfarm-control":
        raise CFError("release_invalid","Control release product mismatch")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.-]+)?",str(m.get("version",""))):
        raise CFError("release_invalid","A semantic control release version is required")
    if m.get("channel") not in ("stable","beta","nightly"):
        raise CFError("release_invalid","Unsupported update channel")
    notes=m.get("release_notes",[])
    if not isinstance(notes,list) or len(notes)>20 or any(not isinstance(x,str) or len(x)>1000 for x in notes):
        raise CFError("release_invalid","Release notes must be a bounded list of strings")
    platform=m.get("platform")
    if not isinstance(platform,dict) or set(platform)-{"os","arch"} or platform.get("os") not in ("any","macos","windows","linux") or platform.get("arch") not in ("any","arm64","amd64","x86_64"):
        raise CFError("release_invalid","A supported target platform is required")
    artifact=m.get("artifact")
    if not isinstance(artifact,dict) or set(artifact)-{"path","sha256","size","format"}:
        raise CFError("release_invalid","Control release artifact metadata is invalid")
    path=artifact.get("path","")
    if not isinstance(path,str):
        raise CFError("unsafe_path","Update artifact path is unsafe")
    p=PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\\" in path or ":" in path or p.name!=path.rsplit("/",1)[-1]:
        raise CFError("unsafe_path","Update artifact path is unsafe")
    if not re.fullmatch(r"[0-9a-f]{64}",str(artifact.get("sha256",""))):
        raise CFError("release_invalid","Update artifact SHA-256 is required")
    if not isinstance(artifact.get("size"),int) or not 1<=artifact["size"]<=256*1024*1024:
        raise CFError("release_invalid","Update artifact size is outside the allowed limit")
    if artifact.get("format")!="wheel" or not path.lower().endswith(".whl"):
        raise CFError("release_invalid","Only signed Python wheel updates are supported")

def validate_requirements(text):
    if not text.strip() or len(text)>1024*1024: raise CFError("invalid_lock","Empty/oversized environment lock")
    joined=text.replace("\\\n", " ")
    for raw in joined.splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+(?:\s+--hash=sha256:[0-9a-f]{64})+",line):
            raise CFError("invalid_lock","Only exact versions with wheel hashes are allowed; no URLs, editable installs, or index directives")
