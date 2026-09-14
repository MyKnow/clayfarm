from __future__ import annotations
import contextlib
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any


class FarmError(Exception):
    """A safe, actionable user-facing error."""


class OfflineError(FarmError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def native_path(path: Path) -> Path:
    """Support deep task/artifact paths without changing Windows registry policy."""
    text = str(Path(path).resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return Path(text)


def sqlite_path(path: Path) -> Path:
    """Use one ordinary absolute spelling for Windows SQLite and WAL locking."""
    text=str(Path(path).expanduser().resolve())
    if os.name=="nt":
        if text.startswith("\\\\?\\UNC\\"):
            text="\\\\"+text[8:]
        elif text.startswith("\\\\?\\"):
            text=text[4:]
    return Path(text)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_bytes(path: Path, data: bytes, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if secret:
            os.chmod(name, 0o600)
        os.replace(name, path)
        if os.name != "nt":
            with contextlib.suppress(OSError):
                dfd = os.open(path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def write_json(path: Path, data: Any, secret: bool = False) -> None:
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(), secret)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def new_id() -> str:
    return str(uuid.uuid4())


def check_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as e:
        raise FarmError("Expected a UUID, not a path or arbitrary name.") from e


def safe_key(key: str) -> str:
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,800}", key):
        raise FarmError("Invalid artifact key.")
    if key.startswith("/") or any(p in ("", ".", "..") for p in key.split("/")):
        raise FarmError("Artifact path traversal rejected.")
    return key


def safe_file(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}", name) or name in (".", ".."):
        raise FarmError("Invalid artifact filename.")
    return name


def home_dir() -> Path:
    return Path(os.environ.get("CLAYFARM_HOME", Path.home() / ".clayfarm")).expanduser().resolve()


class ProcessLock:
    """An OS-released lock: stale PID files never prevent reboot recovery."""
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            # Windows byte-range locks prohibit even reading the locked byte.
            # Locking past EOF is supported; no initialization read/write is needed.
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.file.close()
            raise FarmError("Another worker already owns this node. Stop it before starting/updating.") from e
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()
