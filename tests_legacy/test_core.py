from __future__ import annotations
import concurrent.futures
import copy
import io
import json
import os
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from clayfarm.cli import submit_job, collect_result, demo
from clayfarm.executors import mock_glb, run
from clayfarm.journal import Journal
from clayfarm.local import LocalBackend
from clayfarm.png import encode, decode, contact_sheet
from clayfarm.remote import SupabaseBackend, ApiError, base_url, CHUNK
from clayfarm.resources import can_run
from clayfarm.spec import validate_spec, plan, task_fingerprint
from clayfarm.util import FarmError, OfflineError, ProcessLock, canonical, digest, new_id, safe_key, write_json, native_path
from clayfarm.worker import Worker


class Clock:
    def __init__(self): self.value=1000
    def __call__(self): return self.value
    def tick(self,n=121): self.value+=n


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.temp.name=str(native_path(Path(self.temp.name))); self.root=Path(self.temp.name)
        self.clock=Clock(); self.central=self.root/"central"
        self.caller=LocalBackend(self.central,"caller","caller",self.clock)
        self.a=LocalBackend(self.central,"worker-a","worker",self.clock)
        self.b=LocalBackend(self.central,"worker-b","worker",self.clock)
        for w in (self.a,self.b): w.rpc("heartbeat",{"capabilities":["mock","blender","sf3d","triposr"]})
        self.image=self.root/"input.png"; self.image.write_bytes(encode(16,16,bytes([123,234,45,255])*256))
        self.spec=validate_spec({"name":"hammer"})

    def tearDown(self): self.temp.cleanup()

    def job(self,engines=None):
        return submit_job(self.caller,self.root/"caller-home",self.spec,[self.image],engines or ["mock"],{"agent":"test","session":"same-caller"})["job_id"]

    def task(self,w=None,slot="gpu",**extra): return (w or self.a).rpc("claim",{"slot":slot,"seconds":120,**extra})

    def finish(self,client,task,content=b"fake-glb"):
        local=self.root/new_id(); local.write_bytes(content); sha=digest(local)
        key=f"{client.farm_id}/{client.user_id}/{task['id']}/{task['attempt_id']}/{sha}-mesh.glb"
        client.upload(local,key,self.root/"upload")
        output={"mock":False,"metrics":{"hard_pass":True},"files":[{"role":"mesh","name":"mesh.glb","sha256":sha,"size":len(content),"path":key}]}
        return client.rpc("finish",{"task_id":task["id"],"attempt_id":task["attempt_id"],"output":output}),output

    def worker(self,client=None,home=None,**extra):
        cfg={"home":str(home or self.root/"worker-home"),"allow_mock":True,"gpu_min_ram_mb":0,"cpu_min_ram_mb":0,"min_disk_free_mb":0,"allow_battery":True,**extra}
        w=Worker(cfg,client or self.a); w.refresh(); return w

    def test_atomic_claim_has_single_winner(self):
        self.job()
        clients=[LocalBackend(self.central,f"parallel-{i}",clock=self.clock) for i in range(12)]
        for c in clients:c.rpc("heartbeat",{"capabilities":["mock"]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            claims=list(pool.map(lambda c:self.task(c),clients))
        self.assertEqual(sum(x is not None for x in claims),1)

    def test_five_workers_run_distinct_candidates(self):
        jid=self.job(["sf3d","triposr"])
        a=self.task(); b=self.task(self.b)
        self.assertNotEqual(a["id"],b["id"])
        self.assertIsNone(self.task(LocalBackend(self.central,"unregistered",clock=self.clock)))
        self.assertEqual(len(self.caller.rpc("get",{"id":jid})["tasks"]),16)

    def test_gpu_slot_limit(self):
        self.job(["sf3d","triposr"]); self.assertIsNotNone(self.task()); self.assertIsNone(self.task())

    def test_cpu_and_gpu_slots_are_independent(self):
        self.job(["sf3d","triposr"])
        t=self.task(); self.finish(self.a,t)
        self.assertIsNotNone(self.task(slot="cpu")); self.assertIsNotNone(self.task(slot="gpu"))

    def test_reclaimed_local_pending_output_is_not_recomputed(self):
        jid=self.job(); worker=self.worker(); first=self.task()
        worker.execute_task(first)
        self.assertEqual(worker.journal.state(first["id"]),"pending")
        self.clock.tick(); replacement=self.task()
        self.assertNotEqual(first["attempt_id"],replacement["attempt_id"])
        with patch("clayfarm.worker.execute",side_effect=AssertionError("must reuse durable output")):
            worker.execute_task(replacement)
        self.assertEqual(worker.journal.entry(first["id"])["task"]["attempt_id"],replacement["attempt_id"])
        worker.flush()
        self.assertEqual(worker.journal.state(first["id"]),"committed")

    def test_malformed_spec_types_fail_cleanly(self):
        for spec in ({"name":[]},{"name":"bad","views":[[]]},{"name":"bad","views":[{}]}):
            with self.subTest(spec=spec), self.assertRaises(FarmError): validate_spec(spec)

    def test_compute_done_releases_slot_before_upload(self):
        self.job(["sf3d","triposr"])
        t=self.task()
        self.a.rpc("computed",{"task_id":t["id"],"attempt_id":t["attempt_id"]})
        nxt=self.task(); self.assertIsNotNone(nxt); self.assertNotEqual(t["id"],nxt["id"])
        self.assertIsNone(self.task(self.b,"cpu")) # parent still not committed

    def test_expired_lease_reclaimed_with_new_fence(self):
        self.job(); t1=self.task(); self.clock.tick(); t2=self.task(self.b)
        self.assertEqual(t1["id"],t2["id"]); self.assertNotEqual(t1["attempt_id"],t2["attempt_id"])
        accepted,_=self.finish(self.a,t1); self.assertFalse(accepted["accepted"])
        accepted,_=self.finish(self.b,t2); self.assertTrue(accepted["accepted"])

    def test_expired_even_without_replacement_cannot_commit(self):
        self.job(); t=self.task(); self.clock.tick(); result,_=self.finish(self.a,t)
        self.assertFalse(result["accepted"])

    def test_renew_keeps_lease(self):
        self.job(); t=self.task(); self.clock.tick(100)
        self.assertTrue(self.a.rpc("renew",{"task_id":t["id"],"attempt_id":t["attempt_id"],"seconds":120})["accepted"])
        self.clock.tick(50); self.assertIsNone(self.task(self.b))

    def test_finish_is_idempotent(self):
        self.job(); t=self.task(); first,output=self.finish(self.a,t)
        second=self.a.rpc("finish",{"task_id":t["id"],"attempt_id":t["attempt_id"],"output":output})
        self.assertTrue(first["accepted"]); self.assertTrue(second["already_committed"])

    def test_child_waits_for_parent_publication(self):
        self.job(); t=self.task(); self.assertIsNone(self.task(self.b,"cpu"))
        self.finish(self.a,t)
        self.assertEqual(self.task(self.b,"cpu")["kind"],"process")

    def test_three_failures_bound_retry_and_propagate(self):
        jid=self.job()
        for _ in range(3):
            t=self.task(); self.a.rpc("fail",{"task_id":t["id"],"attempt_id":t["attempt_id"],"error":{"code":"oom"}})
        self.assertIsNone(self.task())
        view=self.caller.rpc("get",{"id":jid})
        self.assertTrue(all(t["status"]=="failed" for t in view["tasks"]))

    def test_three_crashes_bound_retry(self):
        jid=self.job()
        for _ in range(3): self.assertIsNotNone(self.task()); self.clock.tick()
        self.assertIsNone(self.task())
        self.assertTrue(all(t["status"]=="failed" for t in self.caller.rpc("get",{"id":jid})["tasks"]))

    def test_cancellation_fences_running_tasks(self):
        jid=self.job(); t=self.task(); self.caller.rpc("cancel",{"id":jid})
        self.assertFalse(self.a.rpc("renew",{"task_id":t["id"],"attempt_id":t["attempt_id"]})["accepted"])
        self.assertIsNone(self.task(self.b))

    def test_worker_cannot_cancel(self):
        jid=self.job()
        with self.assertRaisesRegex(FarmError,"caller"):self.a.rpc("cancel",{"id":jid})

    def test_only_originating_caller_can_approve_or_cancel(self):
        jid=self.job(); another=LocalBackend(self.central,"other-caller","caller",self.clock)
        with self.assertRaisesRegex(FarmError,"originating"):another.rpc("cancel",{"id":jid})

    def test_upload_before_commit(self):
        self.job(); t=self.task()
        output={"files":[{"path":f"{self.a.farm_id}/{self.a.user_id}/{t['id']}/{t['attempt_id']}/no-file.glb"}]}
        with self.assertRaisesRegex(FarmError,"upload_before_commit"):
            self.a.rpc("finish",{"task_id":t["id"],"attempt_id":t["attempt_id"],"output":output})

    def test_foreign_artifact_scope_rejected(self):
        self.job(); t=self.task()
        with self.assertRaisesRegex(FarmError,"scope"):
            self.a.rpc("finish",{"task_id":t["id"],"attempt_id":t["attempt_id"],"output":{"files":[{"path":"another-user/file.glb"}]}})

    def test_submission_retry_same_id(self):
        jid=self.job(); request=json.loads((self.root/"caller-home/submissions"/jid/"request.json").read_text())
        result=self.caller.rpc("submit",request)
        self.assertTrue(result["existing"]); self.assertEqual(len(self.caller.rpc("get",{"id":jid})["tasks"]),8)
        request["request_hash"]="0"*64
        with self.assertRaisesRegex(FarmError,"idempotency"):self.caller.rpc("submit",request)

    def test_worker_recovers_output_after_network_failure(self):
        jid=self.job(); w=self.worker(); self.assertTrue(w.step("gpu"))
        self.assertEqual(len(w.journal.entries(["pending"])),1)
        with patch.object(self.a,"upload",side_effect=OfflineError("network down")):
            with self.assertRaises(OfflineError):w.flush()
        self.clock.tick()
        rebooted=self.worker(); rebooted.flush()
        self.assertEqual(len(rebooted.journal.entries(["pending"])),0)
        states=[t["status"] for t in self.caller.rpc("get",{"id":jid})["tasks"]]
        self.assertEqual(states.count("done"),1)

    def test_late_outbox_never_overwrites_winner(self):
        jid=self.job(); w=self.worker(); w.step("gpu"); self.clock.tick()
        other=self.task(self.b); self.finish(self.b,other,b"winner")
        w.flush(); self.assertEqual(len(w.journal.entries(["superseded"])),1)
        t=next(t for t in self.caller.rpc("get",{"id":jid})["tasks"] if t["kind"]=="reconstruct")
        self.assertEqual(t["lease_owner"],self.b.user_id)

    def test_offline_prefetched_work_adopted_when_reconnected(self):
        self.job(); w=self.worker(offline_speculation=True)
        w.prefetch("gpu"); self.assertEqual(len(w.journal.entries(["cached"])),1)
        with patch.object(self.a,"rpc",side_effect=OfflineError("partition")):
            self.assertTrue(w.offline_step("gpu"))
        self.assertEqual(len(w.journal.entries(["pending"])),1)
        w.flush(); self.assertEqual(len(w.journal.entries(["committed"])),1)

    def test_offline_speculation_disabled_by_default(self):
        self.job(); w=self.worker(); w.prefetch("gpu")
        self.assertFalse(w.offline_step("gpu"))

    def test_prefetch_does_not_lease(self):
        self.job(); w=self.worker(); w.prefetch("gpu")
        self.assertIsNotNone(self.task(self.b))

    def test_prefetch_cannot_clobber_pending_outbox(self):
        self.job(); w=self.worker(); task=self.task(); w.journal.save(task,"pending",{"files":[]})
        w.journal.cache_if_safe(task); self.assertEqual(w.journal.state(task["id"]),"pending")

    def test_local_result_reused_as_downstream_input_cache(self):
        self.job(); w=self.worker(); w.step("gpu"); w.flush()
        downstream=self.task(slot="cpu")
        with patch.object(self.a,"download",side_effect=AssertionError("unexpected re-download")):
            self.assertTrue(w.cache(downstream).is_file())

    def test_preview_fanout_is_independent(self):
        self.job(); r=self.task(); self.finish(self.a,r); p=self.task(slot="cpu"); self.finish(self.a,p)
        a=self.task(slot="cpu"); b=self.task(self.b,slot="cpu")
        self.assertEqual(a["kind"],"preview"); self.assertEqual(b["kind"],"preview"); self.assertNotEqual(a["id"],b["id"])

    def test_fixture_cannot_pass_as_real_asset(self):
        result=demo(self.root/"demo")
        self.assertEqual(result["ready_candidates"],[])
        self.assertEqual(result["status"],"diagnostic_only")
        self.assertTrue(result["diagnostic_candidates"][0]["mock"])
        caller=LocalBackend(self.root/"demo/coordinator","local-caller","caller")
        with self.assertRaisesRegex(FarmError,"mock"):
            caller.rpc("approve",{"id":result["job_id"],"task_id":result["diagnostic_candidates"][0]["process_task"]})


class PureTests(unittest.TestCase):
    def test_unknown_semantic_part_edit_rejected(self):
        with self.assertRaisesRegex(FarmError,"Unsupported"):
            validate_spec({"name":"hammer","handle":{"thickness":"+20%"}})

    def test_nan_and_negative_values_rejected(self):
        for change in ({"height_m":float("nan")},{"axis_scale":[1,float("inf"),1]},{"target_triangles":-1}):
            with self.assertRaises(FarmError): validate_spec({"name":"x",**change})

    def test_boolean_not_accepted_as_triangle_integer(self):
        with self.assertRaises(FarmError):validate_spec({"name":"x","target_triangles":True})

    def test_duplicate_seed_candidates_rejected(self):
        blob={"sha256":"a"*64,"path":"x/y","name":"a.png","size":1}
        with self.assertRaisesRegex(FarmError,"distinct"):
            plan(new_id(),validate_spec({"name":"x"}),[blob],["sf3d","sf3d"])

    def test_identical_reference_deduplicated(self):
        blob={"sha256":"a"*64,"path":"x/y","name":"a.png","size":1}
        tasks=plan(new_id(),validate_spec({"name":"x"}),[blob,blob],["sf3d"])
        self.assertEqual(sum(t["kind"]=="reconstruct" for t in tasks),1)

    def test_png_roundtrip_and_corruption(self):
        data=bytes(range(256))*4; encoded=encode(16,16,data)
        self.assertEqual(decode(encoded),(16,16,data))
        corrupted=bytearray(encoded); corrupted[40]^=255
        with self.assertRaises(FarmError):decode(corrupted)

    def test_valid_glb_fixture_header(self):
        b=mock_glb(); magic,ver,n=struct.unpack("<4sII",b[:12])
        self.assertEqual((magic,ver,n),(b"glTF",2,len(b)))

    def test_path_traversal_rejected(self):
        for p in ("../secrets","a/../../b","/abs","a\\b","a//b","a/./b"):
            with self.assertRaises(FarmError):safe_key(p)

    def test_https_origin_required(self):
        for url in ("http://host","https://user:pass@host","https://host/path","https://host?secret=x"):
            with self.assertRaises(FarmError):base_url(url)

    def test_privileged_key_rejected(self):
        cfg={"url":"https://example.supabase.co","publishable_key":"sb_secret_do-not-use","user_id":"u","farm_id":"f"}
        with self.assertRaisesRegex(FarmError,"secret"):SupabaseBackend(cfg)

    def test_fingerprint_ignores_lease_but_not_input(self):
        task={"id":"one","kind":"process","capability":"blender","payload":{"spec":{"name":"x"}},"parent_output":{"files":[]},"attempt_id":"old"}
        newer={**task,"attempt_id":"new"}; self.assertEqual(task_fingerprint(task),task_fingerprint(newer))
        newer["parent_output"]={"files":["changed"]}; self.assertNotEqual(task_fingerprint(task),task_fingerprint(newer))

    def test_resource_admission(self):
        stats={"gpu":{"free_mb":7300,"utilization":2,"temperature":55},"memory_available_mb":16000,"on_battery":False}
        self.assertTrue(can_run("gpu",{},stats))
        for patch_ in ({"gpu":{**stats["gpu"],"free_mb":6000}},{"on_battery":True},{"paused":True}):
            self.assertFalse(can_run("gpu",{}, {**stats,**patch_}))

    def test_process_timeout_terminates_child(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(FarmError,"time budget"):
                run([sys.executable,"-c","import time;time.sleep(30)"],root,root/"log.txt",1,threading.Event())

    def test_single_worker_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"worker.lock"
            with ProcessLock(path):
                with self.assertRaises(FarmError):
                    with ProcessLock(path):pass
            with ProcessLock(path):pass


class TusTests(unittest.TestCase):
    def client(self):
        return SupabaseBackend({"url":"https://example.supabase.co","publishable_key":"public-key","user_id":"u","farm_id":"f","email":"x","password":"y"})

    def test_interrupted_upload_resumes_at_server_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); file=root/"mesh.glb"; file.write_bytes(b"x"*(CHUNK+37))
            client=self.client(); state={"offset":0,"created":0,"break":True,"patch_offsets":[]}
            endpoint=client.storage+"/storage/v1/upload/resumable/opaque"
            def http(url,method="GET",data=None,headers=None,**kw):
                if "/object/authenticated/" in url:raise ApiError(404,"not_found")
                if method=="POST":state["created"]+=1;return 201,{"Location":endpoint},b""
                if method=="HEAD":return 200,{"Upload-Offset":str(state["offset"])},b""
                if method=="PATCH":
                    off=int(headers["Upload-Offset"]);state["patch_offsets"].append(off)
                    if off==CHUNK and state["break"]:state["break"]=False;raise OfflineError("dropped")
                    state["offset"]+=len(data);return 204,{"Upload-Offset":str(state["offset"])},b""
                raise AssertionError(method)
            with patch.object(client,"http",side_effect=http):
                with self.assertRaises(OfflineError):client.upload(file,"f/u/task/mesh.glb",root/"state")
                client.upload(file,"f/u/task/mesh.glb",root/"state")
            self.assertEqual(state["created"],1);self.assertEqual(state["offset"],file.stat().st_size)
            self.assertEqual(state["patch_offsets"],[0,CHUNK,CHUNK])

    def test_foreign_tus_location_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); file=root/"x.glb";file.write_bytes(b"123")
            client=self.client()
            with patch.object(client,"_exists",return_value=False), patch.object(client,"http",return_value=(201,{"Location":"https://attacker.example/steal"},b"")):
                with self.assertRaisesRegex(FarmError,"location"):client.upload(file,"f/u/file.glb",root)

    def test_download_sha_rejects_corruption(self):
        class Response(io.BytesIO):
            status=200;headers={}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); client=self.client()
            blob={"path":"f/u/mesh.glb","size":3,"sha256":"0"*64}
            with patch.object(client,"http",return_value=Response(b"bad")):
                with self.assertRaisesRegex(FarmError,"SHA"):client.download(blob,root/"target.glb")
            self.assertFalse((root/"target.glb").exists())


if __name__=="__main__": unittest.main()
