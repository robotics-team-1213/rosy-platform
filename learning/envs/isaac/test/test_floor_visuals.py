from pathlib import Path
import sys
import shutil
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tools/sim/isaac'))
from floor_visuals import floor_visuals, map_visual_profile

MAP = ROOT / 'middleware/perception/map/map_v2_fleet'


@pytest.mark.parametrize('fault', [None, 'missing_plane', 'missing_material', 'write_failed',
                                  'disabled_plane', 'extra_collision', 'wrong_resolved_material'])
def test_sdk_ground_has_one_material_bound_collision_surface(monkeypatch, fault):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from floor_visuals import configure_ground_collision, verify_ground_collision

    mesh, plane, material = (MagicMock() for _ in range(3))
    mesh.GetTypeName.return_value = 'Mesh'
    plane.GetTypeName.return_value = 'Plane' if fault != 'missing_plane' else ''
    plane.GetPath.return_value = '/ground/collisionPlane'
    mesh.GetPath.return_value = '/ground/geom'
    material.GetPath.return_value = '/material' if fault != 'wrong_resolved_material' else '/wrong'
    for prim in (mesh, plane, material):
        prim.HasAPI.return_value = True
    enabled = {mesh: True, plane: fault != 'disabled_plane'}
    bindings = {mesh: ['/material'] if fault != 'missing_material' else [], plane: []}
    for prim in (mesh, plane):
        prim.GetCollisionEnabledAttr.return_value.Get.side_effect = lambda p=prim: enabled[p]
        prim.GetCollisionEnabledAttr.return_value.Set.side_effect = (
            lambda value, p=prim: enabled.update({p: value}) if fault != 'write_failed' else None)
        prim.GetRelationship.return_value.GetTargets.side_effect = lambda p=prim: bindings[p]
    stage = MagicMock()
    stage.GetPrimAtPath.side_effect = {'/ground/geom': mesh, '/ground/collisionPlane': plane,
                                     '/material': material}.__getitem__
    extra = MagicMock()
    extra.GetPath.return_value = '/ground/extra'
    extra.HasAPI.return_value = True
    extra.GetCollisionEnabledAttr.return_value.Get.return_value = True
    stage.Traverse.return_value = [mesh, plane] + ([extra] if fault == 'extra_collision' else [])
    binding_api = MagicMock()
    binding_api.return_value.ComputeBoundMaterial.return_value = (material, None)
    def bind(value, *, materialPurpose):
        assert value is material and materialPurpose == 'physics'
        bindings[plane] = ['/material']
    binding_api.Apply.return_value.Bind.side_effect = bind
    monkeypatch.setitem(sys.modules, 'pxr', SimpleNamespace(
        UsdPhysics=SimpleNamespace(CollisionAPI=lambda prim: prim, MaterialAPI=object()),
        UsdShade=SimpleNamespace(Material=lambda prim: prim, MaterialBindingAPI=binding_api)))
    if fault:
        with pytest.raises(RuntimeError):
            configure_ground_collision(stage, '/ground')
        if fault in ('missing_plane', 'missing_material', 'disabled_plane'):
            assert enabled[mesh] and not bindings[plane]
    else:
        result = configure_ground_collision(stage, '/ground')
        assert enabled == {mesh: False, plane: True}
        assert result == dict(collider='/ground/collisionPlane', visual_collision=False, material='/material')
        assert configure_ground_collision(stage, '/ground') == result
        enabled[mesh] = True
        with pytest.raises(RuntimeError):
            verify_ground_collision(stage, '/ground', result)
        assert enabled[mesh]  # Reset verification must not silently repair a regression.


def test_native_ground_and_paint_use_shared_world_values():
    profile = map_visual_profile(MAP)
    assert profile['ground_colour'] == (.13, .14, .13)
    assert profile['ground_size'] == 5.
    assert profile['paint_pose'] == (0., 0., .001, 0., 0., 0.)
    assert profile['planes'] == floor_visuals(MAP)


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


@pytest.mark.parametrize('change', ['missing_texture', 'escaped_texture', 'rotated_parent',
                                   'nonfinite_pose', 'invalid_ground_size', 'nonfinite_paint'])
def test_invalid_shared_assets_fail_before_rendering(tmp_path, change):
    map_root = tmp_path / 'map'
    shutil.copytree(MAP / 'textures', map_root / 'textures')
    tree = ET.parse(MAP / 'training-curved/worlds/map_v2_fleet_real.world')
    carpet = tree.find('./world/model[@name="carpet"]')
    if change in ('missing_texture', 'escaped_texture'):
        carpet.find('.//albedo_map').text = 'model://control/map/map_v2_fleet/' + (
            '../outside.png' if change == 'escaped_texture' else 'textures/missing.png')
        (tmp_path / 'outside.png').write_bytes(b'existing external asset')
    elif change == 'invalid_ground_size':
        tree.find('./world/model[@name="ground_plane"]/link/visual/geometry/plane/size').text = '100 nan'
    elif change == 'nonfinite_paint':
        tree.find('./world/model[@name="road_lines"]/pose').text = '0 0 nan 0 0 0'
    else:
        carpet.find('pose').text = '0 0 0 0 .1 0' if change == 'rotated_parent' else 'nan 0 0 0 0 0'
    target = map_root / 'training-curved/worlds/map_v2_fleet_real.world'
    target.parent.mkdir(parents=True)
    tree.write(target)
    with pytest.raises(ValueError):
        map_visual_profile(map_root)
