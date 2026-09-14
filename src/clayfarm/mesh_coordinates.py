"""Canonicalize the verified TripoSR export at the GLB boundary.

GLB consumers use glTF Y-up. A scene root rotation preserves binary geometry,
normals, materials and existing hierarchy, unlike editing POSITION alone.
"""
import json
import struct

from .util import FarmError

CONTRACT = 'triposr-viewer-to-gltf-v1'
# TripoSR tsr.utils.to_gradio_3d_orientation: Rx(-90) then Ry(+90).
# Column-major matrix: (x,y,z) -> (-y,z,-x).
_ROTATION = [0, 0, -1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1]
_YAW_ONLY = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1]


def triposr_to_gltf(raw: bytes) -> bytes:
    """Convert only known TripoSR output; never guess orientation from bounds."""
    try:
        magic, version, size, length, kind = struct.unpack_from('<4sIIII', raw)
        if magic != b'glTF' or version != 2 or size != len(raw) or kind != 0x4E4F534A:
            raise ValueError('header')
        if length % 4 or 20 + length > size:
            raise ValueError('JSON chunk')
        doc = json.loads(raw[20:20 + length])
        # Validate chunk framing, including the unchanged binary payload.
        position = 20 + length
        while position < size:
            chunk_length, _ = struct.unpack_from('<II', raw, position)
            if chunk_length % 4 or position + 8 + chunk_length > size:
                raise ValueError('chunk')
            position += 8 + chunk_length
        asset = doc['asset']
        if asset.get('version') != '2.0':
            raise ValueError('asset version')
        previous = asset.get('extras', {}).get('clayfarm_coordinate_contract')
        if previous == CONTRACT:
            return raw
        rotation = _YAW_ONLY if previous == 'triposr-zup-to-gltf-yup-v1' else _ROTATION
        nodes, scenes = doc['nodes'], doc['scenes']
        if not isinstance(nodes, list) or not isinstance(scenes, list) or not nodes or not scenes:
            raise ValueError('scene graph')
        count = len(nodes)
        for scene in scenes:
            roots = scene.get('nodes', [])
            if not isinstance(roots, list) or any(type(i) is not int or not 0 <= i < count for i in roots):
                raise ValueError('scene roots')
            if not roots:
                continue
            scene['nodes'] = [len(nodes)]
            nodes.append({'name': 'ClayFarm_TripoSR_Viewer_Orientation', 'children': roots, 'matrix': rotation})
        asset.setdefault('extras', {})['clayfarm_coordinate_contract'] = CONTRACT
        body = json.dumps(doc, separators=(',', ':'), allow_nan=False).encode('utf-8')
        body += b' ' * (-len(body) % 4)
        tail = raw[20 + length:]
        return struct.pack('<4sIIII', b'glTF', 2, 20 + len(body) + len(tail), len(body), kind) + body + tail
    except (ValueError, TypeError, KeyError, AttributeError, struct.error, UnicodeError) as exc:
        raise FarmError('Invalid TripoSR GLB coordinate data') from exc
