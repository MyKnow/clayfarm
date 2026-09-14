"""TripoSR's raw Z-up export must enter the shared queue as glTF Y-up."""
import json
import os
import struct
import threading

import pytest

from clayfarm.executors import execute, mock_glb
from clayfarm.util import FarmError


def unpack(raw):
    length = struct.unpack_from('<I', raw, 12)[0]
    return json.loads(raw[20:20 + length]), raw[20 + length:]


def pack(doc, tail):
    body = json.dumps(doc).encode()
    body += b' ' * (-len(body) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20 + len(body) + len(tail), len(body), 0x4E4F534A) + body + tail


def raw_zup_fixture():
    doc, tail = unpack(mock_glb())
    # A four-sided upright asymmetric fixture: width=1, depth=2, height=4.
    vertices = [(-.5, -1, 0), (.5, -1, 0), (0, 1, 0), (0, 0, 4)]
    binary = b''.join(struct.pack('<3f', *point) for point in vertices)
    tail = tail[:8] + binary + tail[8 + len(binary):]
    doc['accessors'][0].update(min=[-.5, -1, 0], max=[.5, 1, 4])
    return pack(doc, tail)


def test_triposr_conversion_preserves_binary_and_nested_scene_transforms():
    from clayfarm.mesh_coordinates import triposr_to_gltf
    raw = raw_zup_fixture()
    doc, tail = unpack(raw)
    doc['nodes'] = [{'translation': [2, 3, 4], 'children': [1]}, {'mesh': 0}]
    doc['scenes'].append({'nodes': [0]})
    raw = pack(doc, tail)
    converted = triposr_to_gltf(raw)
    result, new_tail = unpack(converted)
    assert new_tail == tail
    assert result['nodes'][:2] == doc['nodes']
    # Upstream viewer orientation: Rx(-90), then Ry(+90).
    for scene in result['scenes']:
        root = result['nodes'][scene['nodes'][0]]
        assert root['children'] == [0]
        assert root['matrix'] == [0, 0, -1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1]
    assert triposr_to_gltf(converted) == converted


def test_up_only_diagnostic_can_be_upgraded_without_second_tilt():
    from clayfarm.mesh_coordinates import triposr_to_gltf
    doc, tail = unpack(raw_zup_fixture())
    doc['asset']['extras'] = {'clayfarm_coordinate_contract': 'triposr-zup-to-gltf-yup-v1'}
    old_rotation = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]
    doc['nodes'].append({'children': [0], 'matrix': old_rotation})
    doc['scenes'][0]['nodes'] = [1]
    result, _ = unpack(triposr_to_gltf(pack(doc, tail)))
    assert result['nodes'][1]['matrix'] == old_rotation
    # Only the remaining Y rotation is applied to a prior up-only diagnostic.
    assert result['nodes'][-1]['matrix'] == [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1]


@pytest.mark.parametrize('raw', [b'glTFbad', mock_glb()[:-1], b'wrong' + mock_glb()[5:]])
def test_corrupt_glb_is_rejected(raw):
    from clayfarm.mesh_coordinates import triposr_to_gltf
    with pytest.raises(FarmError):
        triposr_to_gltf(raw)


def test_reconstruction_publishes_canonical_mesh(tmp_path, monkeypatch):
    import clayfarm.executors as executors
    repo = tmp_path / 'repo'; repo.mkdir()
    raw = raw_zup_fixture()
    def fake_run(argv, *_args):
        out = tmp_path / 'work' / 'reconstruction' / '0'
        out.mkdir(parents=True)
        (out / 'mesh.glb').write_bytes(raw)
    monkeypatch.setattr(executors, 'run', fake_run)
    for engine in ('triposr', 'sf3d'):
        work = tmp_path / 'work'
        if work.exists():
            import shutil
            shutil.rmtree(work)
        result = execute({'kind': 'reconstruct', 'capability': engine,
                          'payload': {'engine': engine, 'spec': {'name': 'fixture'}}},
                         tmp_path / 'input.png', work,
                         {'engines': {engine: {'ready': True, 'repo': str(repo), 'python': 'python'}}},
                         threading.Event())
        data = (work / 'reconstruction' / '0' / 'mesh.glb').read_bytes()
        if engine == 'triposr':
            assert data != raw
            assert result['provenance']['mesh_up_axis'] == 'Y'
            assert result['provenance']['source_up_axis'] == 'Z'
        else:
            assert data == raw


@pytest.mark.skipif(not os.environ.get('CLAYFARM_TEST_BLENDER'), reason='Requires real Blender')
def test_legacy_parent_new_parent_and_revision_keep_upright(tmp_path):
    from clayfarm.mesh_coordinates import triposr_to_gltf
    raw = tmp_path / 'raw.glb'; raw.write_bytes(raw_zup_fixture())
    canonical = tmp_path / 'canonical.glb'; canonical.write_bytes(triposr_to_gltf(raw.read_bytes()))
    cfg = {'blender': os.environ['CLAYFARM_TEST_BLENDER'], 'cpu_threads': 2}
    parent = {'provenance': {'capability': 'triposr', 'kind': 'reconstruct'}, 'mock': False}
    for name, source in [('legacy', raw), ('new', canonical)]:
        task = {'kind': 'process', 'capability': 'blender', 'parent_output': parent,
                'payload': {'spec': {'name': name, 'height_m': 1}}}
        result = execute(task, source, tmp_path / name, cfg, threading.Event())
        assert result['metrics']['hard_pass']
        assert result['metrics']['dimensions_m'] == pytest.approx([.5, .25, 1], abs=1e-5)
        # A CPU revision consumes the canonical Blender output without re-rotation.
        task['parent_output'] = result
        revised = execute(task, tmp_path / name / 'mesh.glb', tmp_path / (name + '-revision'), cfg, threading.Event())
        assert revised['metrics']['dimensions_m'] == pytest.approx([.5, .25, 1], abs=1e-5)
