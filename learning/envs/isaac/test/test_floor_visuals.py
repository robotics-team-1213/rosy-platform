from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tools/sim/isaac'))
from floor_visuals import floor_visuals

MAP = ROOT / 'middleware/perception/map/map_v2_fleet'


def test_shared_floor_assets_have_metric_scale_and_source_poses():
    visuals = floor_visuals(MAP)
    carpet = [v for v in visuals if v['name'].startswith('carpet_')]
    assert len(visuals) == 23 and len(carpet) == 18
    assert {v['size'] for v in carpet} == {(.5, .5)}
    assert {v['pose'][2] for v in carpet} == {.0003}
    assert {v['texture'] for v in carpet} == {(MAP / 'textures/carpet_grey.png').resolve()}
    assert min(v['pose'][0] for v in carpet) == -1.25
    assert max(v['pose'][0] for v in carpet) == 1.25
    outline = next(v for v in visuals if v['name'] == 'reference_square_A_link_outline')
    assert outline['pose'] == (-1.26, .49, .002, 0., 0., 0.)
    assert outline['size'] == (.13, .17) and outline['texture'] is None
    dock = next(v for v in visuals if v['name'] == 'dock_tag_7_link_face')
    assert dock['pose'] == (-.74979, 0., .01409, 0., -.436332, 0.)
    assert dock['texture'] == (MAP / 'textures/dock_tag_7.png').resolve()


@pytest.mark.parametrize('change', ['missing_texture', 'escaped_texture', 'rotated_parent', 'nonfinite_pose'])
def test_invalid_shared_assets_fail_before_rendering(tmp_path, change):
    tree = ET.parse(MAP / 'training-curved/worlds/map_v2_fleet_real.world')
    carpet = tree.find('./world/model[@name="carpet"]')
    if change in ('missing_texture', 'escaped_texture'):
        carpet.find('.//albedo_map').text = 'model://control/map/map_v2_fleet/' + (
            '../../outside.png' if change == 'escaped_texture' else 'textures/missing.png')
    else:
        carpet.find('pose').text = '0 0 0 0 .1 0' if change == 'rotated_parent' else 'nan 0 0 0 0 0'
    target = tmp_path / 'training-curved/worlds/map_v2_fleet_real.world'
    target.parent.mkdir(parents=True)
    tree.write(target)
    with pytest.raises(ValueError):
        floor_visuals(tmp_path)
