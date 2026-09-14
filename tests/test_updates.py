import io
import time
import zipfile
from pathlib import Path

import pytest

from clayfarm_control.api import create_app
from clayfarm_control.common import CFError, atomic_json, sha
from clayfarm_control.demo import FixtureVerifier, fixture_client
from clayfarm_control.device import new_key
from clayfarm_control.releases import sign_manifest, verify_manifest
from clayfarm_control.registry import load_registry
from clayfarm_control.updates import client_check, host_target, stage_update, validate_wheel, version_key
from clayfarm_control.db import Database


def wheel_bytes(version="0.4.1"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"clayfarm_control-{version}.dist-info/METADATA", f"Metadata-Version: 2.1\nName: clayfarm-control\nVersion: {version}\n")
        archive.writestr(f"clayfarm_control-{version}.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
    return stream.getvalue()


def release(root, key, version="0.4.1"):
    data = wheel_bytes(version)
    (root / "artifacts").mkdir(parents=True)
    (root / "artifacts" / "clayfarm-control.whl").write_bytes(data)
    manifest = {
        "schema_version": 1,
        "id": f"control-{version.replace('.', '-')}-release",
        "kind": "control_release",
        "sequence": 1,
        "issued_at": time.time() - 1,
        "expires_at": time.time() + 3600,
        "product": "clayfarm-control",
        "version": version,
        "channel": "stable",
        "platform": {"os": host_target()[0], "arch": host_target()[1]},
        "release_notes": ["Versioned CLI update test"],
        "artifact": {"path": "artifacts/clayfarm-control.whl", "sha256": sha(data), "size": len(data), "format": "wheel"},
    }
    envelope = sign_manifest(manifest, key["private"], "release")
    atomic_json(root / "manifest.json", envelope)
    return envelope, data


def test_control_release_manifest_is_signed_and_pinned(tmp_path):
    key = new_key()
    manifest = release(tmp_path / "updates", key)[0]
    assert verify_manifest(manifest, {"release": key["public"]})["kind"] == "control_release"


def test_version_order_puts_stable_after_prerelease():
    assert version_key("0.4.0.dev1") < version_key("0.4.0") < version_key("0.4.1")


def test_update_check_and_download_use_signed_server_feed(tmp_path):
    key = new_key()
    updates = tmp_path / "updates"
    envelope, data = release(updates, key)
    db = Database("sqlite:///" + str(tmp_path / "db")); db.init()
    app = create_app(db, load_registry(), FixtureVerifier(), artifact_root=tmp_path / "artifacts", update_root=updates, release_trust={"release": key["public"]})
    client = fixture_client(tmp_path / "client", app, "fixture-user")
    atomic_json(client.home / "trust.json", {"release": key["public"]})
    checked = client_check(client, client.home)
    assert checked["update_available"] is True and checked["version"] == "0.4.1"
    result = stage_update(client, client.home, envelope)
    assert Path(result["downloaded"]).read_bytes() == data
    client.http.close(); db.engine.dispose()


def test_update_artifact_and_wheel_validation_reject_tampering(tmp_path):
    key = new_key(); updates = tmp_path / "updates"; envelope, data = release(updates, key)
    path = updates / "artifacts" / "clayfarm-control.whl"
    path.write_bytes(data + b"tampered")
    db = Database("sqlite:///" + str(tmp_path / "db")); db.init()
    app = create_app(db, load_registry(), FixtureVerifier(), artifact_root=tmp_path / "artifacts", update_root=updates, release_trust={"release": key["public"]})
    client = fixture_client(tmp_path / "client", app, "fixture-user")
    with pytest.raises(CFError, match="failed its hash"):
        client.call("GET", "/v1/updates/artifacts/" + envelope["signed"]["id"], anonymous=True)
    client.http.close(); db.engine.dispose()


def test_validate_wheel_requires_control_metadata(tmp_path):
    path = tmp_path / "bad.whl"; path.write_bytes(wheel_bytes("0.4.1"))
    validate_wheel(path, "0.4.1")
    with pytest.raises(CFError): validate_wheel(path, "0.4.2")
