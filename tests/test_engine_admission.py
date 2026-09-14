from unittest.mock import Mock

import pytest

from clayfarm_control.central_worker import CentralWorker, runtime_config
from clayfarm_control.common import CFError, atomic_json


def worker(tmp_path, monkeypatch):
    import clayfarm_control.central_worker as module
    stats = {'gpu': {'free_mb': 3999, 'total_mb': 6141, 'utilization': 0, 'temperature': 50},
             'memory_available_mb': 9000, 'on_battery': False, 'paused': False}
    monkeypatch.setattr(module, 'telemetry', lambda cfg: stats)
    monkeypatch.setattr(module, 'capabilities', lambda cfg: ['triposr', 'sf3d', 'blender'])
    monkeypatch.setattr(module, 'engine_verified', lambda cfg, cap: True)
    cfg = {'home': str(tmp_path), 'engine_limits': {'triposr': {'min_free_vram_mb': 3840, 'gpu_min_ram_mb': 8192}}}
    return CentralWorker(cfg, Mock()), stats


def test_measured_triposr_limit_does_not_lower_sf3d_limit(tmp_path, monkeypatch):
    w, stats = worker(tmp_path, monkeypatch)
    w.refresh()
    assert w.caps == ['triposr', 'blender']
    assert w.can_run_slot('gpu')
    assert 'min_free_vram_mb' not in w.cfg
    stats['gpu']['free_mb'] = 3800
    w.backend.rpc.reset_mock()
    assert w.step('gpu') is False
    assert w.caps == ['blender']
    assert all(c.args[0] != 'claim' for c in w.backend.rpc.call_args_list)


@pytest.mark.parametrize('change', [
    {'on_battery': True}, {'memory_available_mb': None}, {'memory_available_mb': 8191},
    {'gpu': None}, {'paused': True}])
def test_node_will_not_advertise_cuda_with_unsafe_or_unknown_budget(tmp_path, monkeypatch, change):
    w, stats = worker(tmp_path, monkeypatch)
    stats.update(change)
    w.refresh()
    assert 'triposr' not in w.caps
    assert not w.can_run_slot('gpu')


@pytest.mark.parametrize('limits', [
    {'triposr': {'min_free_vram_mb': True}}, {'triposr': {'min_free_vram_mb': -1}},
    {'unknown': {'min_free_vram_mb': 3840}}, {'triposr': {'allow_mock': True}},
    {'triposr': {'gpu_min_ram_mb': '8192'}}, []])
def test_invalid_engine_policy_is_rejected(tmp_path, limits):
    atomic_json(tmp_path / 'execution.json', {'engine_limits': limits})
    with pytest.raises(CFError, match='engine'):
        runtime_config(tmp_path)
