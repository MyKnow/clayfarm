from __future__ import annotations
import hashlib, json, os, tempfile, time, uuid
from pathlib import Path
from urllib.parse import urlsplit

class CFError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)

def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()

def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def file_sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): h.update(block)
    return h.hexdigest()

def uid() -> str: return str(uuid.uuid4())
def now() -> float: return time.time()

def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".cf-")
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(canonical(value)); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def read_json(path: Path, default=None):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e: raise CFError("invalid_json",f"Cannot read JSON: {path.name}") from e

def secure_url(url: str, *, loopback: bool=False) -> str:
    p=urlsplit(url)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise CFError("invalid_url","A URL without credentials, query, or fragment is required")
    if p.scheme!="https" and not(loopback and p.scheme=="http" and p.hostname in ("127.0.0.1","localhost","::1")):
        raise CFError("https_required","HTTPS is required except explicitly configured loopback development")
    return url.rstrip("/")

def safe_id(value: str) -> str:
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}",value) or ".." in value:
        raise CFError("invalid_id","Invalid identifier")
    return value

def safe_relative(root: Path, name: str) -> Path:
    if "\\" in name or ":" in name: raise CFError("unsafe_path","Invalid artifact path")
    p=Path(name)
    if p.is_absolute() or ".." in p.parts or not p.parts: raise CFError("unsafe_path","Path traversal rejected")
    result=(root/p).resolve()
    if not result.is_relative_to(root.resolve()): raise CFError("unsafe_path","Path escapes root")
    return result
