#!/usr/bin/env python3
"""Create a signed control-plane update manifest.

The private Ed25519 key is read from ``CLAYFARM_UPDATE_PRIVATE_KEY`` and is
never accepted as a command-line argument.  Copy the wheel into the configured
server update root before publishing the resulting JSON file.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path, PurePosixPath

from clayfarm_control.common import atomic_json, file_sha
from clayfarm_control.releases import sign_manifest
from clayfarm_control.updates import host_target, validate_wheel


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--artifact-path", required=True, help="POSIX path relative to the server update root")
    parser.add_argument("--channel", choices=["stable", "beta", "nightly"], default="stable")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--os", dest="os_name", choices=["any", "macos", "windows", "linux"])
    parser.add_argument("--arch", choices=["any", "arm64", "amd64", "x86_64"])
    args = parser.parse_args(argv)
    private = os.environ.get("CLAYFARM_UPDATE_PRIVATE_KEY")
    if not private:
        parser.error("CLAYFARM_UPDATE_PRIVATE_KEY is required")
    if args.sequence <= 0:
        parser.error("sequence must be positive")
    artifact = PurePosixPath(args.artifact_path)
    if artifact.is_absolute() or ".." in artifact.parts or "\\" in args.artifact_path or ":" in args.artifact_path or not args.artifact_path.lower().endswith(".whl"):
        parser.error("artifact path must be a safe relative .whl path")
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        parser.error("wheel does not exist")
    try:
        validate_wheel(wheel, args.version)
    except Exception as exc:
        parser.error(str(exc))
    os_name, arch = host_target()
    manifest = {
        "schema_version": 1,
        "id": f"control-{args.version.replace('.', '-')}-{args.sequence}-{args.os_name or os_name}-{args.arch or arch}",
        "kind": "control_release",
        "sequence": args.sequence,
        "issued_at": time.time(),
        "expires_at": time.time() + 90 * 24 * 3600,
        "product": "clayfarm-control",
        "version": args.version,
        "channel": args.channel,
        "platform": {"os": args.os_name or os_name, "arch": args.arch or arch},
        "release_notes": args.note,
        "artifact": {"path": args.artifact_path, "sha256": file_sha(wheel), "size": wheel.stat().st_size, "format": "wheel"},
    }
    atomic_json(args.output, sign_manifest(manifest, private, args.key_id))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
