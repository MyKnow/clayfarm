# v0.2.2 Windows worker startup hotfix

Reported error: `sqlite3.OperationalError: locking protocol` while initializing the worker journal on Windows/Python 3.11.

The worker passed an extended Windows path to SQLite while CLI status passed an ordinary path. Journal now normalizes both aliases to the same absolute ordinary path. Extended paths remain enabled for deep artifact paths. Connections also close if PRAGMA setup fails. Database contents, WAL mode and FULL synchronization are preserved; no database or sidecar files are deleted and no job is resubmitted.

The exact reported exception did not reproduce on this Windows machine using Python 3.11.16, even when holding a connection through the other path alias. This is a targeted fix for an observed code inconsistency, not proof of the remote machine's root cause or recovery. Existing pending-result preservation and concurrent access through both aliases are covered by new tests. The recipient must verify restart success.

## Existing Park Hamin node

1. Extract the new personal ZIP and open PowerShell in the clayfarm directory. This is necessary to find install.ps1; ordinary assetnode commands work from any directory.
2. If another worker is running, request `assetnode stop` and wait for its process to exit. A failed startup traceback already exited. Do not terminate unrelated Python/Conda processes.
3. Run `.\install.ps1 -BootstrapRuntime`. This replaces the zipapp, keeps a previous copy, and preserves the existing enrollment, engine installations and work/outbox. There is no need to re-enroll or repeat model warm. The installer refuses to replace an active locked worker.
4. In a new PowerShell run `assetnode --version` (expected 0.2.2), `assetnode status`, then `assetnode worker`.
5. If `locking protocol` persists, stop here and report the new traceback plus `assetnode status` output after removing secrets, if any. Do not delete worker.sqlite, worker.sqlite-wal, worker.sqlite-shm, work directories or model caches. Do not initialize a blank home to hide the failure.

The already submitted helmet job is 225b5d7c-e4ac-482f-9955-4302c8f6a760. No duplicate submission is necessary. The worker still needs available GPU memory, low GPU utilization and external power. This hotfix does not lower resource admission thresholds.

The attached gpu-01.enrollment.json is for this recipient only and is not needed for an in-place update. Do not print or redistribute it.
