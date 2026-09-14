"""Run with CLAYFARM_TEST_BLENDER=/absolute/path/to/blender for real smoke tests."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from clayfarm.cli import selftest_blender, submit_job, collect_result, upload_input, dispatch, parser
from clayfarm.executors import execute, mock_glb, run
from clayfarm.local import LocalBackend
from clayfarm.resources import blender_ready, blender_signature, capabilities
from clayfarm.spec import validate_spec, plan, VIEWS
from clayfarm.util import FarmError, native_path, new_id, read_json, write_json
from clayfarm.worker import Worker


class ContractTests(unittest.TestCase):
    def test_six_views_and_cpu_only_revision_dag(self):
        spec=validate_spec({"name":"clay","material":{"preset":"sage"},"lod_ratios":[.5,.25],"collider":"box"})
        self.assertEqual(spec["material"]["mode"],"clay_single")
        tasks=plan(new_id(),spec,[],["sf3d"],raw_mesh={"sha256":"a"*64})
        self.assertEqual(len(tasks),7)
        self.assertEqual([t["payload"]["view"] for t in tasks[1:]],list(VIEWS))
        self.assertTrue(all(t["slot"]=="cpu" and t["capability"]=="blender" for t in tasks))
        self.assertTrue(all(t["parent_id"]==tasks[0]["id"] for t in tasks[1:]))

    def test_reject_unsafe_or_unsupported_options(self):
        values=[{"geometry":{"remesh":"voxel"}}, {"geometry":{"voxel_size_ratio":.0001}},
                {"geometry":{"smooth_iterations":True}}, {"geometry":{"merge_distance_ratio":float("nan")}},
                {"lod_ratios":[.5,.6]}, {"lod_ratios":[True]}, {"collider":"mesh"},
                {"material":{"preset":"unknown"}}, {"geometry":{"script":"bad"}}]
        for value in values:
            with self.subTest(value=value), self.assertRaises(FarmError): validate_spec({"name":"bad",**value})

    def test_advertise_only_tested_binary_and_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            binary=Path(folder)/"blender.exe"; binary.write_bytes(b"one")
            cfg={"blender":str(binary)}
            with patch("clayfarm.resources.gpu_stats",return_value=None):
                self.assertNotIn("blender",capabilities(cfg))
                cfg["blender_selftest"]={"signature":blender_signature(cfg)}
                self.assertIn("blender",capabilities(cfg))
                binary.write_bytes(b"changed")
                self.assertFalse(blender_ready(cfg))

    def test_mock_retains_nonapproval_with_new_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            spec=validate_spec({"name":"mock","material":{"preset":"cream"},"collider":"box"})
            result=execute({"kind":"process","capability":"mock","payload":{"spec":spec}},
                           Path(folder)/"input",Path(folder)/"out",{"allow_mock":True},threading.Event())
            self.assertTrue(result["mock"]); self.assertFalse(result["metrics"]["hard_pass"])

    def test_warm_without_cuda_fails_before_install(self):
        from clayfarm.setup import warm
        with patch("clayfarm.setup.gpu_stats",return_value=None):
            with self.assertRaisesRegex(FarmError,"NVIDIA CUDA"):
                warm({},"triposr",None,None,"image.png",install=True)

    def test_render_failure_clears_prior_readiness(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg={"home":folder,"blender_selftest":{"signature":"old"}}
            with patch("clayfarm.executors.execute",side_effect=FarmError("render failed")):
                with self.assertRaises(FarmError): selftest_blender(cfg)
            self.assertNotIn("blender_selftest",read_json(Path(folder)/"config.json"))


@unittest.skipUnless(os.environ.get("CLAYFARM_TEST_BLENDER"),"Set CLAYFARM_TEST_BLENDER for real Blender tests")
class BlenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.temp.name=str(native_path(Path(self.temp.name)))
        self.root=Path(self.temp.name)
        if os.name=="nt": self.root=Path(str(self.root).removeprefix("\\\\?\\"))
        self.cfg={"home":str(self.root/"node"),"blender":os.environ["CLAYFARM_TEST_BLENDER"],
                  "allow_battery":True,"cpu_min_ram_mb":0,"min_disk_free_mb":0,"cpu_threads":2}
    def tearDown(self): self.temp.cleanup()

    def test_selftest_remesh_lods_collider_six_renders(self):
        receipt=selftest_blender(self.cfg)
        self.assertTrue(receipt["blender_smoke_pass"])
        metrics=receipt["metrics"]
        self.assertTrue(metrics["hard_pass"]); self.assertEqual(metrics["non_manifold_edges"],0)
        self.assertEqual(len(metrics["extras"]),3)
        self.assertTrue(blender_ready(read_json(Path(self.cfg["home"])/"config.json")))

    def test_worker_dag_transformed_input_and_revision(self):
        # Multiple parts, parent transform, mirrored scale, dense surface and loose vertex.
        script=self.root/"fixture.py"
        script.write_text('''import bpy,sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.empty_add(location=(3,2,1))
parent=bpy.context.object; parent.rotation_euler.z=.4
for location,scale in [((0,0,0),(-.5,.4,.8)),((.7,0,.7),(.3,.3,.4))]:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,location=location)
    obj=bpy.context.object; obj.scale=scale; obj.parent=parent
data=bpy.data.meshes.new("loose"); data.from_pydata([(0,0,0)],[],[])
bpy.context.collection.objects.link(bpy.data.objects.new("loose",data))
bpy.ops.export_scene.gltf(filepath=sys.argv[-1],export_format="GLB")
''')
        raw=self.root/"input.glb"
        run([self.cfg["blender"],"-b","--python-exit-code","1","--python",str(script),"--",str(raw)],
            self.root,self.root/"fixture.log",120,threading.Event())
        central=self.root/"coordinator"; caller=LocalBackend(central,"caller","caller")
        blob=upload_input(caller,raw,new_id(),self.root/"caller")
        self.cfg["blender_selftest"]={"signature":blender_signature(self.cfg)}
        worker=Worker(self.cfg,LocalBackend(central,"blender-cpu")); worker.refresh()
        caller_home=self.root/"caller"
        write_json(caller_home/"config.json",{"backend":"local","local_root":str(central),"user_id":"caller","role":"caller"})
        # CPU-only node cannot claim reconstruction. It can consume a committed raw GLB.
        self.assertIsNone(worker.backend.rpc("claim",{"slot":"gpu"}))
        for pivot,height in (("bottom_center",.8),("center",.6)):
            spec=validate_spec({"name":"fixture","height_m":height,"pivot":pivot,"target_triangles":300,
                "material":{"preset":"terracotta"},"collider":"box","lod_ratios":[.5],"preview_size":128})
            if pivot=="bottom_center":
                jid=submit_job(caller,caller_home,spec,[],["sf3d"],{"agent":"codex","session":"fixture-test"},raw_mesh=blob)["job_id"]
            else:
                patch_file=self.root/"revision.json"; write_json(patch_file,{"height_m":height,"pivot":pivot})
                previous=jid
                jid=dispatch(parser().parse_args(["--home",str(caller_home),"revise",jid,"--task",candidate["process_task"],"--patch",str(patch_file)]))["job_id"]
                revised=caller.rpc("get",{"id":jid})
                self.assertEqual(revised["job"]["parent_job"],previous)
                self.assertFalse(any(t["kind"]=="reconstruct" for t in revised["tasks"]))
            for _ in range(7):
                self.assertTrue(worker.step("cpu")); worker.flush()
            report=collect_result(caller,jid,self.root/pivot,artifacts=True)
            self.assertTrue(report["all_terminal"]); self.assertEqual(report["failures"],[])
            self.assertEqual(report["caller"]["session"],"fixture-test")
            candidate=report["ready_candidates"][0]; self.assertEqual(len(candidate["previews"]),6)
            metrics=candidate["metrics"]; self.assertTrue(metrics["hard_pass"])
            self.assertAlmostEqual(metrics["dimensions_m"][2],height,places=5)
            self.assertEqual(len(candidate["artifacts"]),5)
            self.assertGreater(metrics["input_triangles"],metrics["triangles"])

    def test_corrupt_input_cannot_reuse_old_outputs(self):
        work=self.root/"process"; work.mkdir()
        for name in ("mesh.glb","mesh.fbx","metrics.json"): (work/name).write_text("stale")
        bad=self.root/"bad.glb"; bad.write_bytes(b"not glb")
        with self.assertRaises(FarmError):
            execute({"kind":"process","capability":"blender","payload":{"spec":{"name":"bad"}}},
                    bad,work,self.cfg,threading.Event())
        self.assertFalse((work/"mesh.glb").exists())


if __name__=="__main__": unittest.main()
