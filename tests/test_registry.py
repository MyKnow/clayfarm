import copy
import pytest
from clayfarm_control.registry import load_registry,plan,validate_registry,ADAPTERS
from clayfarm_control.inventory import bands_for,memory_admission,GIB
from clayfarm_control.common import CFError

def inv(os="windows",gpu=6,apple=None):
    r={"os":os,"ram_total_bytes":(apple or 32)*GIB,"ram_available_bytes":24*GIB,"memory_kind":"unified" if apple else "host_plus_dedicated","devices":[],"backend_candidates":["cpu"],"runtime":{}}
    if apple:r["backend_candidates"] += ["mps","mlx"]
    elif gpu:r["devices"]=[{"id":"gpu0","backend":"cuda","total_bytes":gpu*GIB,"free_bytes":gpu*GIB}];r["backend_candidates"].append("cuda")
    return r

def test_registry_counts():
    r=load_registry();assert len(r["models"])==17;assert len(r["profiles"])==39;assert len(r["hardware_bands"])==11

@pytest.mark.parametrize("memory,band",[(4,"C4"),(6,"C6"),(8,"C8"),(12,"C12"),(16,"C16"),(24,"C24"),(32,"C32")])
def test_cuda_bands(memory,band):assert bands_for(inv(gpu=memory))==[band,"CPU"]

@pytest.mark.parametrize("memory,band",[(16,"A16"),(24,"A24"),(32,"A32")])
def test_apple_bands(memory,band):assert bands_for(inv(os="macos",gpu=0,apple=memory))==[band,"CPU"]

def test_4050_eligible_but_not_ready():
    p=plan(load_registry(),inv(gpu=6),experimental=True)
    s={x["profile_id"]:x for x in p["profiles"]}
    assert s["sd-turbo-cuda"]["candidate"] and not s["sd-turbo-cuda"]["ready"]
    assert "adapter_not_implemented" in s["triposr-lowmem"]["blockers"]

def test_mac_is_not_cpu_only_or_cuda_equivalent():
    p=plan(load_registry(),inv(os="macos",gpu=0,apple=24),experimental=True)
    s={x["profile_id"]:x for x in p["profiles"]}
    assert s["sdxl-mps"]["candidate"] and s["flux2-q4-mlx"]["candidate"]
    assert not s["sdxl-cuda"]["candidate"]
    assert not s["flux2-q4-mlx"]["adapter_implemented"]

def test_duplicate_registry_rejected():
    r=load_registry();r["profiles"].append(copy.deepcopy(r["profiles"][0]))
    with pytest.raises(CFError):validate_registry(r)

def test_registry_cannot_mark_nodes_ready():
    r=load_registry();r["profiles"][0]["node_ready"]=True
    with pytest.raises(CFError):validate_registry(r)

def test_unknown_memory_not_zero():assert not memory_admission(inv(),{"peak_host_bytes":1},"cuda")[0]

def test_unified_memory_is_shared():
    r=inv(os="macos",apple=24);r["ram_available_bytes"]=12*GIB;r["runtime"]={"mps_recommended_bytes":20*GIB}
    assert not memory_admission(r,{"peak_host_bytes":6*GIB,"peak_device_bytes":6*GIB},"mps")[0]

def test_no_sum_of_two_gpu_vram():
    r=inv(gpu=6);r["devices"].append(dict(r["devices"][0],id="gpu1"))
    assert not memory_admission(r,{"peak_host_bytes":GIB,"peak_device_bytes":8*GIB},"cuda")[0]

def test_missing_mps_runtime_budget():
    r=inv(os="macos",apple=24)
    assert memory_admission(r,{"peak_host_bytes":GIB,"peak_device_bytes":GIB},"mps")[1]=="mps_budget_unknown"


def test_unimplemented_forged_state_never_ready():
    from clayfarm_control.registry import get_profile,profile_digest
    r=load_registry();p=get_profile(r,"flux2-q4-mlx")
    states={p["id"]:{"status":"verified","profile_digest":profile_digest(r,p)}}
    result=plan(r,inv(os="macos",gpu=0,apple=24),experimental=True,installed=states)
    assert not next(x for x in result["profiles"] if x["profile_id"]==p["id"])["ready"]
