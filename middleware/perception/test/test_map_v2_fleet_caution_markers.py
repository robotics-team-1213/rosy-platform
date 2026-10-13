"""Real warning paint is shared by Gazebo and Isaac, separate from crosswalks."""
import struct
import xml.etree.ElementTree as ET

import pytest
import yaml

from test_map_v2_fleet_scene import BUNDLE, SOURCE, _load


def test_warning_meshes_match_shared_geometry_and_all_worlds(tmp_path):
    build = _load('build_world')
    parts = build.caution_meshes()
    assert {p['id'] for p in parts} == {'NE', 'NW', 'SE', 'SW'}
    assert len(parts) == 8
    rules = yaml.safe_load((BUNDLE / 'lane_rules.yaml').read_text())
    assert len(rules['caution_markers']['placements']) == 4
    assert len(yaml.safe_load((BUNDLE / 'lane_graph.yaml').read_text())['crosswalks']) == 2
    build.build(SOURCE, tmp_path)
    for part in parts:
        path = 'meshes/' + part['name'] + '.stl'
        data = (tmp_path / path).read_bytes()
        assert data == (BUNDLE / path).read_bytes()
        assert struct.unpack_from('<I', data, 80)[0] == 2
        for i, triangle in enumerate(part['triangles']):
            vertices = struct.unpack_from('<12fH', data, 84 + 50 * i)[3:12]
            assert vertices == pytest.approx([v for point in triangle for v in point])
        for world_path in ('worlds/map_v2_fleet.world', 'worlds/map_v2_fleet_real.world',
                           'training-curved/worlds/map_v2_fleet_real.world'):
            world = ET.parse(tmp_path / world_path)
            visual = world.find(f".//model[@name='{part['name']}']/link/visual")
            assert visual is not None
            assert world.find(f".//model[@name='{part['name']}']/link/collision") is None
            assert visual.find('.//uri').text.endswith('/' + path)
            assert [float(v) for v in visual.find('./material/diffuse').text.split()] == [*part['colour'], 1]
            assert (tmp_path / world_path).read_bytes() == (BUNDLE / world_path).read_bytes()
