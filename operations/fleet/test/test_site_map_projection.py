"""STL is untrusted background geometry; projection never invents roads."""
import importlib
import math
import struct
from pathlib import Path
import hashlib

import pytest

from core_common.protocol.site_drawing import DrawingTransform


def converter():
    try:
        return importlib.import_module('fleet.server.site_map_projection')
    except ModuleNotFoundError as exc:
        if exc.name != 'fleet.server.site_map_projection':
            raise
        pytest.fail('STL converter is not implemented')


def binary(triangles):
    return b'solid binary'.ljust(80, b'\0') + struct.pack('<I', len(triangles)) + b''.join(
        struct.pack('<12fH', 0, 0, 1, *sum((tuple(p) for p in triangle), ()), 0)
        for triangle in triangles)


def mesh(tmp_path, data):
    path = tmp_path / 'drawing.stl'
    path.write_bytes(data)
    return path


def registration(**changes):
    return DrawingTransform(**{'plane': 'xy', 'unit': 'm', 'source_origin': [0, 0],
                               'map_origin_m': [0, 0], 'heading_rad': 0, 'scale': 1, **changes})


def test_binary_solid_header_is_not_ascii(tmp_path):
    module = converter()
    path = mesh(tmp_path, binary([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]]))
    info = module.inspect_stl(path)
    assert info['format'] == 'binary_stl' and info['triangle_count'] == 1
    assert info['bounds_3d'] == [[0, 0, 0], [1, 1, 0]]
    result = module.project_stl(path, registration())
    assert len(result['segments']) == 3
    assert result == module.project_stl(path, registration())
    assert result['asset_sha256'] == info['asset_sha256']


def test_ascii_grammar_and_missing_final_newline(tmp_path):
    module = converter()
    data = b'solid cad\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid cad'
    path = mesh(tmp_path, data)
    assert module.inspect_stl(path)['format'] == 'ascii_stl'
    assert len(module.project_stl(path, registration())['segments']) == 3
    for bad in (data.replace(b'endfacet', b'ignored'), data + b'\n<script>',
                data.replace(b'vertex 1 0 0', b'vertex inf 0 0')):
        with pytest.raises(ValueError):
            module.inspect_stl(mesh(tmp_path, bad))


def test_truncated_and_nonfinite_mesh_rejected(tmp_path):
    module = converter()
    data = binary([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]])
    for bad in (data[:-1], data + b'x', binary([[(math.nan, 0, 0), (1, 0, 0), (0, 1, 0)]]),
                binary([]), b'solid empty\nendsolid empty'):
        with pytest.raises(ValueError):
            module.inspect_stl(mesh(tmp_path, bad))


@pytest.mark.parametrize('plane,axes', [('xy', (0, 1)), ('xz', (0, 2)), ('yz', (1, 2))])
@pytest.mark.parametrize('unit,factor', [('m', 1), ('cm', 100), ('mm', 1000)])
def test_xy_xz_yz_units_and_origins(tmp_path, plane, axes, unit, factor):
    module = converter()
    points = []
    for a, b in ((10, 20), (11, 20), (10, 21)):
        point = [0, 0, 0]
        point[axes[0]], point[axes[1]] = a * factor, b * factor
        points.append(point)
    path = mesh(tmp_path, binary([points]))
    result = module.project_stl(path, registration(plane=plane, unit=unit,
        source_origin=[10 * factor, 20 * factor], map_origin_m=[2, 3], heading_rad=math.pi / 2))
    assert result['bounds_m'][0] == pytest.approx([1, 3])
    assert result['bounds_m'][1] == pytest.approx([2, 4])
    assert max(math.dist(*segment) for segment in result['segments']) == pytest.approx(math.sqrt(2))
    with pytest.raises(ValueError):
        module.project_stl(path, registration(unit=unit, map_origin_m=[1000, 1000], scale=1e300))


def test_triangle_and_segment_budgets(tmp_path, monkeypatch):
    module = converter()
    path = mesh(tmp_path, binary([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]] * 2))
    assert len(module.project_stl(path, registration())['segments']) == 3
    monkeypatch.setattr(module, 'MAX_TRIANGLES', 1)
    with pytest.raises(ValueError):
        module.inspect_stl(path)
    monkeypatch.setattr(module, 'MAX_TRIANGLES', 200_000)
    monkeypatch.setattr(module, 'MAX_SEGMENTS', 2)
    with pytest.raises(ValueError):
        module.project_stl(path, registration())


def test_existing_design_source_is_read_only_geometry_for_every_explicit_plane():
    module = converter()
    path = Path(__file__).resolve().parents[3] / 'middleware/perception/map/map_v2_fleet/260919 MAP FILE.STL'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    inspected = module.inspect_stl(path)
    assert inspected['asset_sha256'] == before and inspected['triangle_count'] == 1768
    hashes = set()
    for plane in ('xy', 'xz', 'yz'):
        result = module.project_stl(path, registration(plane=plane, unit='mm'))
        assert result['segments'] and result['asset_sha256'] == before
        assert not {'places', 'edges', 'facilities', 'robot_pose'} & result.keys()
        hashes.add(result['projection_sha256'])
    assert len(hashes) == 3
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
