"""Signed control-plane update feed and explicit CLI installation helpers.

The API only serves manifests and artifacts that are signed by a pinned release
key.  The client verifies the same envelope before it stores or installs a
wheel.  Network checks are opt-in through ``clayfarm update``; credentials and
arbitrary URLs never enter the update path.
"""
from __future__ import annotations

import os
import platform as host_platform
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

from clayfarm.util import atomic_bytes

from . import __version__
from .common import CFError, atomic_json, canonical, file_sha, read_json, safe_id, safe_relative, sha
from .releases import verify_manifest

MAX_UPDATE_BYTES = 256 * 1024 * 1024
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.-]([0-9A-Za-z.-]+))?$")


def version_key(value: str):
    """Return a comparable key for the PEP-440-like versions used by releases."""
    match = _VERSION.fullmatch(str(value))
    if not match:
        raise CFError("invalid_version", "Release version is invalid")
    pre = match.group(4)
    if pre is None:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), 1, ())
    tokens = []
    for token in re.split(r"[.-]", pre):
        tokens.append((0, int(token)) if token.isdigit() else (1, token.lower()))
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), 0, tuple(tokens))


def host_target() -> tuple[str, str]:
    os_name = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(host_platform.system(), host_platform.system().lower())
    arch = host_platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64"}.get(arch, arch)
    return os_name, arch


def target_matches(manifest: dict, os_name: str | None = None, arch: str | None = None) -> bool:
    target = manifest.get("platform", {})
    return (target.get("os") in ("any", os_name) and target.get("arch") in ("any", arch))


def _manifest_files(root: Path):
    root = Path(root).resolve()
    single = root / "manifest.json"
    if single.is_file():
        yield single
    directory = root / "manifests"
    if directory.is_dir():
        yield from sorted(directory.glob("*.json"))


def _verified_envelopes(root: Path, trust: dict):
    for path in _manifest_files(root):
        try:
            envelope = read_json(path)
            manifest = verify_manifest(envelope, trust)
        except CFError:
            continue
        if manifest.get("kind") == "control_release":
            yield envelope


def latest_update(root: Path, trust: dict, *, channel: str = "stable", platform_os: str | None = None, platform_arch: str | None = None):
    if channel not in ("stable", "beta", "nightly"):
        raise CFError("invalid_channel", "Unsupported update channel")
    candidates = []
    for envelope in _verified_envelopes(Path(root), trust):
        manifest = envelope["signed"]
        if manifest.get("product") != "clayfarm-control" or manifest.get("channel") != channel:
            continue
        if platform_os is not None and platform_arch is not None and not target_matches(manifest, platform_os, platform_arch):
            continue
        candidates.append(envelope)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (version_key(item["signed"]["version"]), item["signed"]["sequence"]))


def update_artifact(root: Path, trust: dict, release_id: str) -> tuple[Path, dict]:
    safe_id(release_id)
    for envelope in _verified_envelopes(Path(root), trust):
        manifest = envelope["signed"]
        if manifest.get("id") != release_id:
            continue
        artifact = manifest["artifact"]
        relative = artifact["path"]
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts or "\\" in relative or ":" in relative:
            raise CFError("unsafe_path", "Update artifact path is unsafe")
        path = safe_relative(Path(root), relative)
        if not path.is_file() or path.stat().st_size != artifact["size"] or file_sha(path) != artifact["sha256"]:
            raise CFError("update_artifact_invalid", "Published update artifact is missing or failed its hash")
        return path, manifest
    raise CFError("update_not_found", "Signed update release was not found", 404)


def _state_path(home: Path) -> Path:
    return Path(home) / "update-state.json"


def _platform_query() -> tuple[str, str]:
    return host_target()


def client_check(client, home: Path, *, channel: str = "stable") -> dict:
    os_name, arch = _platform_query()
    payload = client.call("GET", f"/v1/updates/check?channel={channel}&platform_os={os_name}&platform_arch={arch}", anonymous=True)
    if not isinstance(payload, dict):
        raise CFError("update_feed_invalid", "Update feed returned an invalid response")
    envelope = payload.get("latest")
    current = __version__
    state = read_json(_state_path(home), {})
    if not envelope:
        return {"update_available": False, "current_version": current, "channel": channel, "target": {"os": os_name, "arch": arch}}
    trust = read_json(Path(home) / "trust.json", {})
    manifest = verify_manifest(envelope, trust, highwater=int(state.get("sequence", 0)))
    if state.get("sequence") == manifest["sequence"] and state.get("manifest_sha256") not in (None, sha(canonical_manifest(manifest))):
        raise CFError("release_equivocation", "The same release sequence has different content")
    if not target_matches(manifest, os_name, arch):
        return {"update_available": False, "current_version": current, "channel": channel, "target": {"os": os_name, "arch": arch}, "reason": "platform_mismatch"}
    newer = version_key(manifest["version"]) > version_key(current)
    result = {"update_available": newer, "current_version": current, "channel": channel, "target": {"os": os_name, "arch": arch}, "release_id": manifest["id"], "version": manifest["version"], "release_notes": manifest.get("release_notes", [])}
    if newer:
        result["manifest"] = envelope
    return result


def canonical_manifest(manifest: dict) -> bytes:
    return canonical(manifest)


def stage_update(client, home: Path, envelope: dict) -> dict:
    trust = read_json(Path(home) / "trust.json", {})
    state = read_json(_state_path(home), {})
    manifest = verify_manifest(envelope, trust, highwater=int(state.get("sequence", 0)))
    os_name, arch = _platform_query()
    if not target_matches(manifest, os_name, arch):
        raise CFError("platform_mismatch", "This update is for another OS or architecture")
    artifact = manifest["artifact"]
    data = client.call("GET", f"/v1/updates/artifacts/{manifest['id']}", anonymous=True, download=True)
    if len(data) != artifact["size"] or sha(data) != artifact["sha256"]:
        raise CFError("update_hash_mismatch", "Downloaded update failed its signed hash")
    target = safe_relative(Path(home) / "updates", PurePosixPath(artifact["path"]).name)
    atomic_bytes(target, data)
    staged = {"sequence": manifest["sequence"], "manifest_sha256": sha(canonical_manifest(manifest)), "manifest": envelope, "bundle": str(target), "downloaded_at": time.time(), "status": "downloaded"}
    atomic_json(_state_path(home), staged)
    return {"downloaded": str(target), "release_id": manifest["id"], "version": manifest["version"], "sha256": artifact["sha256"], "size": len(data)}


def validate_wheel(path: Path, version: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise ValueError
            metadata = archive.read(metadata_files[0]).decode("utf-8", "strict")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeError, ValueError) as exc:
        raise CFError("update_package_invalid", "Signed update is not a valid wheel") from exc
    fields = {}
    for line in metadata.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key.lower(), value)
    if fields.get("name", "").lower() != "clayfarm-control" or fields.get("version") != version:
        raise CFError("update_package_mismatch", "Wheel metadata does not match the signed release")


def apply_update(home: Path, envelope: dict, bundle: Path) -> dict:
    trust = read_json(Path(home) / "trust.json", {})
    state = read_json(_state_path(home), {})
    manifest = verify_manifest(envelope, trust, highwater=int(state.get("sequence", 0)))
    bundle = Path(bundle).expanduser().resolve()
    artifact = manifest["artifact"]
    if not bundle.is_file() or bundle.stat().st_size != artifact["size"] or file_sha(bundle) != artifact["sha256"]:
        raise CFError("update_hash_mismatch", "Local update package failed its signed hash")
    validate_wheel(bundle, manifest["version"])
    try:
        pip_probe = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CFError("update_installer_missing", "The current Python environment has no usable pip; reinstall it with install.sh or install.ps1") from exc
    if pip_probe.returncode:
        raise CFError("update_installer_missing", "The current Python environment has no usable pip; reinstall it with install.sh or install.ps1")
    atomic_json(_state_path(home), {**state, "sequence": manifest["sequence"], "manifest_sha256": sha(canonical_manifest(manifest)), "manifest": envelope, "bundle": str(bundle), "status": "applying", "attempted_at": time.time()})
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}}
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(bundle)], capture_output=True, text=True, env=env, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CFError("update_install_failed", "The update installer could not be started; the downloaded package is retained") from exc
    if result.returncode:
        raise CFError("update_install_failed", "The update package could not be installed; the downloaded package is retained")
    try:
        smoke = subprocess.run([sys.executable, "-c", "import clayfarm_control; print(clayfarm_control.__version__)"], capture_output=True, text=True, env=env, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CFError("update_smoke_failed", "The installed CLI failed its version smoke check; inspect the retained update state") from exc
    installed = smoke.stdout.strip()
    if installed != manifest["version"]:
        raise CFError("update_smoke_failed", "The installed CLI version does not match the signed release")
    atomic_json(_state_path(home), {**state, "sequence": manifest["sequence"], "manifest_sha256": sha(canonical_manifest(manifest)), "manifest": envelope, "bundle": str(bundle), "status": "applied", "active_version": installed, "applied_at": time.time()})
    return {"updated": True, "version": installed, "release_id": manifest["id"], "rollback": "Use the previous signed wheel and run clayfarm update apply --bundle PATH"}
