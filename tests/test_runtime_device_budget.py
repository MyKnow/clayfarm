import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from clayfarm_control import runtime


def test_cuda_calibration_budget_applies_before_model_loading(tmp_path, monkeypatch):
    calls=[]
    cuda=SimpleNamespace(is_available=lambda:True,
        get_device_properties=lambda device:SimpleNamespace(total_memory=6*1024**3),
        set_per_process_memory_fraction=lambda fraction:calls.append(('budget',fraction)))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(cuda=cuda))
    def execute(*args):
        calls.append(('execute',None));return {'status':'verified'}
    monkeypatch.setattr(runtime,'execute',execute)
    request=tmp_path/'request.json';result=tmp_path/'receipt.json'
    request.write_text(json.dumps({'profile':{'backend':'cuda'},'spec':{},'out':str(tmp_path),'device_budget_bytes':3*1024**3}))
    monkeypatch.setattr(sys,'argv',['runtime',str(request),str(result)])
    assert runtime.main()==0
    assert calls==[('budget',.5),('execute',None)]


def test_model_manager_derives_cuda_budget_from_current_free_memory(tmp_path,monkeypatch):
    from clayfarm_control.models import Models
    from clayfarm_control.registry import load_registry,get_profile,profile_digest
    from clayfarm_control.common import CFError
    registry=load_registry();manager=Models(tmp_path,registry);pid='sd-turbo-cuda'
    monkeypatch.setattr(manager,'environment_fingerprint',lambda python:'fixture-env')
    state={'status':'installed_unverified','python':sys.executable,'environment_fingerprint':'fixture-env',
           'profile_digest':profile_digest(registry,get_profile(registry,pid)),
           'adapter_digest':manager.adapter_digest(pid)}
    monkeypatch.setattr('clayfarm_control.inventory.probe',lambda **kw:{'devices':[{'id':'0','free_bytes':4096*1024**2}]})
    observed={}
    def stop_before_inference(argv,*args,**kwargs):
        observed.update(json.loads(Path(argv[-2]).read_text()))
        raise CFError('test_boundary','Stopped at the isolated process boundary')
    monkeypatch.setattr('clayfarm_control.process.run_isolated',stop_before_inference)
    with pytest.raises(CFError,match='isolated process boundary'):
        manager._run(pid,{'prompt':'fixture'},tmp_path/'run',state)
    assert observed['device_budget_bytes']==3584*1024**2
