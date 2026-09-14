"""Unit contract only; actual CUDA verification runs on the Windows device."""
import sys
from types import SimpleNamespace

from clayfarm_control.adapters.diffusers_image import generate


def test_cuda_receipt_includes_model_load_peak(tmp_path, monkeypatch):
    state = {'peak': 0}
    def reset(): state['peak'] = 0
    class Generator:
        def __init__(self, **kwargs): pass
        def manual_seed(self, seed): return self
    torch = SimpleNamespace(float16='fp16', __version__='fixture', Generator=Generator,
                            cuda=SimpleNamespace(is_available=lambda: True,
                                                 reset_peak_memory_stats=reset,
                                                 synchronize=lambda: None,
                                                 max_memory_reserved=lambda: state['peak']))
    class Pipe:
        def to(self, backend):
            state['peak'] = 9000  # Cold load needs more than the later forward pass.
            return self
        def __call__(self, **kwargs):
            state['peak'] = max(state['peak'], 6000)
            return SimpleNamespace(images=[SimpleNamespace(size=(512, 512), save=lambda path: path.write_bytes(b'fixture'))])
    monkeypatch.setitem(sys.modules, 'torch', torch)
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(AutoPipelineForText2Image=SimpleNamespace(from_pretrained=lambda *a, **kw: Pipe())))
    profile = {'id': 'sd-turbo-cuda', 'backend': 'cuda', 'settings': {'height': 512, 'width': 512}}
    _, details = generate(profile, {'prompt': 'fixture', 'seed': 0}, tmp_path, tmp_path / 'out')
    assert details['sample_device_bytes'] == 9000
