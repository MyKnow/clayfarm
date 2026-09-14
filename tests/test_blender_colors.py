"""A glTF COLOR_0 primitive with no material still has visible vertex color."""
import json
import os
import struct
import threading

import pytest

from clayfarm.executors import execute, mock_glb
from clayfarm.png import decode


def vertex_colored_glb():
    raw = mock_glb()
    n = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + n])
    binary = raw[28 + n:]
    offset = len(binary)
    binary += struct.pack('<16f', *([.6, .025, .015, 1] * 4))
    doc['buffers'][0]['byteLength'] = len(binary)
    doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': 64, 'target': 34962})
    doc['accessors'].append({'bufferView': 2, 'componentType': 5126, 'count': 4, 'type': 'VEC4'})
    doc['meshes'][0]['primitives'][0]['attributes']['COLOR_0'] = 2
    body = json.dumps(doc).encode(); body += b' ' * (-len(body) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 28 + len(body) + len(binary), len(body), 0x4E4F534A) + body + struct.pack('<I4s', len(binary), b'BIN\0') + binary


@pytest.mark.skipif(not os.environ.get('CLAYFARM_TEST_BLENDER'), reason='Requires real Blender')
def test_color_only_gltf_remains_colored_after_processing_and_cpu_revision(tmp_path):
    raw = tmp_path / 'source.glb'; raw.write_bytes(vertex_colored_glb())
    cfg = {'blender': os.environ['CLAYFARM_TEST_BLENDER'], 'cpu_threads': 2}
    spec = {'name': 'vertex-colored-fixture', 'material': {'mode': 'preserve'}, 'preview_size': 128}
    task = {'kind': 'process', 'capability': 'blender', 'payload': {'spec': spec}}
    for name in ('process', 'revision'):
        work = tmp_path / name
        result = execute(task, raw, work, cfg, threading.Event())
        assert result['metrics']['materials'] > 0
        raw = work / 'mesh.glb'
        preview = execute({'kind': 'preview', 'capability': 'blender', 'payload': {'spec': spec, 'view': 'front'}},
                          raw, tmp_path / (name + '-preview'), cfg, threading.Event())
        from pathlib import Path
        _, _, pixels = decode(Path(preview['files'][0]['local']).read_bytes())
        opaque = [pixels[i:i + 4] for i in range(0, len(pixels), 4) if pixels[i + 3] > 240]
        red = [p for p in opaque if p[0] > 1.5 * p[1] and p[0] > 1.5 * p[2]]
        assert len(opaque) > 100
        assert len(red) > len(opaque) * .75
