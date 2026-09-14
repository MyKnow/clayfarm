"""Behavioral checks for the repository entrypoints; no real account access."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MODULE = importlib.util.spec_from_file_location("clayfarm_repository_runner", ROOT / "tools/clayfarm/run.py")
runner = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(runner)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clayfarm repository ")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.project = self.folder / "project"
        self.policy = self.project / ".asset-factory/config.json"
        self.policy.parent.mkdir(parents=True)
        self.cfg = json.loads((ROOT / ".asset-factory/config.json").read_text(encoding="utf-8"))
        self.save()
        self.home = self.folder / "private-caller"

    def save(self):
        self.policy.write_text(json.dumps(self.cfg), encoding="utf-8")

    def invoke(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return runner.main(["--factory-project", str(self.project), "--home", str(self.home), *argv])

    def test_offline_blocks_all_remote_operations_before_core_dispatch(self):
        commands = [
            ["nodes"], ["doctor", "--online"], ["worker"],
            ["submit", "--concept", "missing.png", "--spec", "missing.json", "--engine", "triposr"],
            ["result", "job"], ["retry-submit", "job"], ["cancel", "job"],
            ["approve", "job", "--task", "task"], ["revise", "job", "--task", "task", "--patch", "missing.json"],
            ["warm", "--engine", "triposr", "--test-image", "missing.png"],
            ["admin-init", "--out", str(self.folder / "enrollments")],
        ]
        for key, value in (("strict_offline", True), ("execution_mode", "local_only")):
            previous = self.cfg[key]
            self.cfg[key] = value
            self.save()
            for args in commands:
                with self.subTest(policy=key, command=args[0]), patch.object(runner, "farm_main") as core:
                    self.assertEqual(self.invoke(args), 2)
                    core.assert_not_called()
            self.cfg[key] = previous

    def test_offline_keeps_local_diagnosis_and_drain_controls(self):
        self.cfg["strict_offline"] = True
        self.save()
        for command in ("doctor", "status", "pause", "resume", "stop", "selftest"):
            with self.subTest(command=command), patch.object(runner, "farm_main", return_value=0) as core:
                self.assertEqual(self.invoke([command]), 0)
                core.assert_called_once()

    def test_private_home_cannot_be_written_in_repository(self):
        self.home = self.project / "private"
        with patch.object(runner, "farm_main") as core:
            self.assertEqual(self.invoke(["enroll", "someone.enrollment.json"]), 2)
            core.assert_not_called()
        self.assertFalse(self.home.exists())

    def test_nonexistent_or_invalid_project_policy_fails_before_network(self):
        self.policy.write_text('{"strict_offline":false}', encoding="utf-8")
        with patch.object(runner, "farm_main") as core:
            self.assertEqual(self.invoke(["nodes"]), 2)
            core.assert_not_called()

    def test_explicit_home_required_instead_of_guessing_worker_identity(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(runner, "farm_main") as core:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(["--factory-project", str(self.project), "nodes"]), 2)
            core.assert_not_called()

    def test_external_home_is_forwarded_without_loss(self):
        with patch.object(runner, "farm_main", return_value=75) as core:
            self.assertEqual(self.invoke(["nodes"]), 75)
            self.assertEqual(core.call_args.args[0], ["--home", str(self.home), "nodes"])

    def test_source_and_factory_entrypoints_run_without_global_install(self):
        for command in ([str(ROOT / "tools/clayfarm/run.py"), "--version"],
                        [str(ROOT / "tools/unity-asset-factory/asset_factory.py"), "--project", str(ROOT), "clayfarm", "--version"]):
            result = subprocess.run([sys.executable, *command], cwd=self.folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "0.2.2")

    def test_factory_offline_policy_cannot_be_replaced_by_child_arguments(self):
        self.cfg["strict_offline"] = True
        self.save()
        base = [sys.executable, str(ROOT / "tools/unity-asset-factory/asset_factory.py"),
                "--project", str(self.project), "clayfarm"]
        blocked = subprocess.run([*base, "--home", str(self.home), "nodes"], capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("OFFLINE_POLICY", blocked.stderr)
        override = subprocess.run([*base, "--factory-project", str(ROOT), "--home", str(self.home), "nodes"], capture_output=True, text=True)
        self.assertEqual(override.returncode, 2)
        self.assertIn("project selected", override.stderr)

    def test_shared_skill_lookup_does_not_create_host_copies(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["skills", "--project", str(ROOT)]), 0)
        self.assertFalse((ROOT / ".claude/skills/clayfarm").exists())
