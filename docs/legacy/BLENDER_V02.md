# Blender pipeline v0.2

The coordinator remains Supabase Auth/Postgres/Storage with Python workers. The local SQLite backend is a test reference, not a network coordinator. No FastAPI, Redis, Ray or Kubernetes has been added.

## Node rollout

Drain every v0.1 worker before submitting v0.2 jobs. Old workers do not understand the extended spec or top/bottom views. Install the same v0.2 bundle on all nodes, run selftest, then restart workers. No SQL schema change is required; the existing output limit of 16 files accommodates the maximum 7 process outputs.

```powershell
# No enrollment or Supabase connection required for this test.
python dist/clayfarm.pyz --home node-test selftest --blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
```

```bash
python3 dist/clayfarm.pyz --home node-test selftest --blender /Applications/Blender.app/Contents/MacOS/Blender
```

For an enrolled node, run `assetnode selftest` using its configured/discovered Blender. It tests voxel remesh, smoothing, decimation, a clay material, two LODs, convex collider and all six CPU renders. A receipt is saved to `blender-smoke/receipt.json`. Only success records Blender readiness. Changing the executable or adapter requires another selftest. Restart a running worker after changing its configuration.

`doctor` distinguishes executable presence from tested readiness. NVIDIA/model checks may be unavailable on Apple workers; those nodes claim only CPU Blender tasks. CUDA engines continue to require `warm --engine ... --test-image ...` before advertisement. Model weights, GPU drivers and Blender are not bundled or silently installed by the worker installer.

Windows installer accepts `-PythonExe <python.exe>` and `-NoPath` for an isolated installation without changing the user PATH. Existing `-BootstrapRuntime` / `--bootstrap-runtime` and optional autostart remain supported.

## Processing contract

1. Import GLB, bake each mesh's world transform (including parents/mirrors), join into one render mesh.
2. Apply Blender XYZ `axis_scale` then normalize height. Remove loose/degenerate geometry and merge nearby vertices.
3. Optional voxel remesh and smoothing, then decimate to the triangle budget.
4. Recalculate face normals and enforce final height/pivot after geometry operations. Set smooth/flat shading and optional clay material.
5. Export `mesh.glb`, `mesh.fbx`, `metrics.json`, optionally `lod1.glb` through `lod3.glb` and `collider.glb`.
6. Separate child tasks render front, three_quarter, right, back, top and bottom. The original caller's `result --artifacts` downloads outputs and builds a labeled contact sheet and report. Columns follow `report.columns`; each candidate occupies one row.

`geometry` accepts `remesh` (`none` default or `voxel`), `voxel_size_ratio` (.005–.1 of longest normalized dimension, default .02), `merge_distance_ratio` (0–.001 of height, default .00001), `smooth_iterations` (0–10, default 0), and `shade_smooth` (boolean, default true). Resolution is bounded to keep remeshing manageable on laptops; it is not an exact memory reservation.

`material.preset` selects `cream`, `terracotta`, or `sage`. Explicit color/roughness override preset defaults. Omitted material retains v0.1 preserve behavior. Voxel remesh requires `clay_single` because it cannot preserve the source UV contract. It can close intended openings or erase thin features and is opt-in.

`lod_ratios` is a decreasing list of up to three ratios (.05 ≤ ratio < 1), each relative to the final base mesh. LODs retain the base coordinate frame; their bounds can change during decimation. `collider` is `none`, `box`, or `convex_hull`. A convex hull above 255 triangles falls back to an enclosing box and records `box_fallback`. Collider files do not create Unity Collider components or LODGroup automatically. Unity import/physics suitability still needs checking.

The report checks geometry, triangle budget, finite nonzero dimensions and actual final pivot/height. It reports non-manifold edges and disconnected components as warnings, not automatic rejection: an open vessel may be intentional. This is not a self-intersection detector, semantic QA, rigging system or full production topology certification.

## Revisions and failures

`revise JOB --task PROCESS_TASK --patch examples/revision.patch.json` creates a new job from the original reconstruction mesh. It does not rerun SF3D/TripoSR or cumulatively decimate a previous result. Patches replace entire top-level fields, including nested `material`/`geometry` objects. Supply desired nested values together. Semantic part edits still require a new concept.

Leases, fenced attempts, retries, durable SQLite journal, offline cache and upload outbox remain in place. Blender Python exceptions now produce a nonzero process exit. Prior outputs are cleared before execution, so failed reruns cannot publish stale files. Short temporary staging avoids Blender's Windows extended-path limitations. Completed outputs are atomically copied back before the existing result journal boundary; a power loss earlier causes bounded recomputation. An abrupt machine/process kill may leave temporary compute files in the OS temp folder; these are never treated as committed results.

## Reproduce verification

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:CLAYFARM_TEST_BLENDER = 'C:\path\to\blender.exe'
python -m unittest discover -s tests -v
python scripts/build_release.py
python dist/clayfarm.pyz demo --out clayfarm-demo
```

Without `CLAYFARM_TEST_BLENDER`, real Blender tests are explicitly skipped. The mock demo still executes five local workers and eight tasks, returns six labeled previews, and rejects approval. Its geometry/previews are fixtures, not AI output. Real tests cover Blender processing plus the CPU worker DAG and a second revised spec using an asymmetric procedural input. These do not establish real five-machine networking, SF3D/TripoSR inference or live Supabase behavior.

References: [Blender 4.5 command arguments](https://docs.blender.org/manual/en/4.5/advanced/command_line/arguments.html), [Remesh modifier API](https://docs.blender.org/api/4.5/bpy.types.RemeshModifier.html), [official Blender builds](https://download.blender.org/release/Blender4.5/).
