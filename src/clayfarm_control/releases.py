"""Small signed-manifest verifier. NOT a complete TUF client (see SECURITY.md)."""
from __future__ import annotations
import base64, re, time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from .common import CFError, canonical, safe_id, sha

def sign_manifest(manifest,private_key,key_id):
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key,validate=True))
    return {"signed":manifest,"signatures":[{"key_id":key_id,"signature":base64.b64encode(key.sign(canonical(manifest))).decode()}]}

def verify_manifest(envelope,trust,*,highwater=0,clock=None):
    if not isinstance(envelope,dict) or set(envelope)!={"signed","signatures"}: raise CFError("release_invalid","Invalid signed envelope")
    m=envelope["signed"]
    if not isinstance(m,dict): raise CFError("release_invalid","Manifest must be an object")
    allowed={"schema_version","id","kind","sequence","issued_at","expires_at","profile_id","profile_digest","adapter","backend","model","environment","license_id","platform","artifact"}
    if set(m)-allowed: raise CFError("release_invalid","Unknown manifest fields")
    if m.get("schema_version")!=1 or m.get("kind") not in ("model_profile","worker_bundle"): raise CFError("release_invalid","Unsupported release schema/kind")
    safe_id(m.get("id",""))
    if not isinstance(m.get("sequence"),int) or m["sequence"]<=0: raise CFError("release_invalid","A positive sequence is required")
    if m["sequence"]<highwater: raise CFError("rollback_attack","Release sequence is older than the locally observed version")
    clock=clock or time.time()
    try:
        if m["issued_at"]>clock+60 or m["expires_at"]<=clock or m["expires_at"]<=m["issued_at"]: raise ValueError()
    except (KeyError,TypeError,ValueError): raise CFError("release_expired","Expired or future-dated release")
    valid=False
    for signature in envelope["signatures"]:
        key=trust.get(signature.get("key_id"))
        if not key: continue
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key,validate=True)).verify(base64.b64decode(signature["signature"],validate=True),canonical(m)); valid=True
        except Exception: continue
    if not valid: raise CFError("untrusted_release","A signature from a locally pinned release key is required")
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

def validate_requirements(text):
    if not text.strip() or len(text)>1024*1024: raise CFError("invalid_lock","Empty/oversized environment lock")
    joined=text.replace("\\\n", " ")
    for raw in joined.splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+(?:\s+--hash=sha256:[0-9a-f]{64})+",line):
            raise CFError("invalid_lock","Only exact versions with wheel hashes are allowed; no URLs, editable installs, or index directives")
