"""Opt-in palletizing jaw v2.1: vendored files, pad geometry from the mesh, finger angles, fixture and planner wiring."""
import json
import math
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f
import model_checks
import palletizing_gripper as g
from prepare_omx_urdf import prepare

CASE, HOLD = 'nominal-palletizing-v21', 'nominal-palletizing-v21-hold'


def test_vendored_package_matches_its_manifest_and_keeps_the_license():
    assert model_checks.check_vendor_manifest(g.ASSETS) == 4  # license, urdf and the two jaw meshes
    assert (g.ASSETS/'LICENSE').read_text().lstrip().startswith('Apache License')


def test_pad_is_the_mesh_face_of_the_raised_tape_pad():
    pad = g.pad()
    assert math.degrees(pad['angle']) == pytest.approx(69.946, abs=.01)  # normal into the jaw, link6 frame
    assert pad['offset']*1000 == pytest.approx(6.3385, abs=.01)  # the plate behind it is at 7.24 mm, its back at 8.2
    assert sorted(abs(v)*1000 for v in pad['along']) == pytest.approx([26.5, 43.5], abs=.01)
    assert pad['z'] == pytest.approx((-.009, .009))
    assert g.description()['tcp'] == (.074, -.0016, 0.)


def test_jaw7_mesh_is_the_mirror_of_jaw6():
    nx, ny = g.pad()['normal']
    hits = 0
    for t in g._triangles(g.ASSETS/'meshes/omx_f/palletizing_jaw7_gear_side_v2_1.stl'):
        if all(abs(nx*t[3*i]-ny*t[3*i+1]-g.pad()['offset']*1000) < .01 for i in range(3)):  # mirrored in y
            hits += 1
    assert hits >= 2


def test_gap_follows_the_pad_geometry_and_is_square_at_the_design_angle():
    # The team's README quotes 29.977 mm at 0.35 rad; the mesh pad faces give 30.977 mm (exactly 1.000 mm more).
    assert g.gap_m(.35)*1000 == pytest.approx(30.977, abs=.01)
    assert [g.gap_m(q) for q in (.2, .3, .4, .5)] == sorted(g.gap_m(q) for q in (.2, .3, .4, .5))
    assert g.gap_m(g.angle_for_gap(.03)) == pytest.approx(.03, abs=1e-7)
    angles = g.finger_angles()
    assert angles['close'] < angles['preopen'] < angles['release']
    assert g.gap_m(angles['close']) == pytest.approx(.027, abs=1e-6)  # 30 mm container less the 3 mm squeeze
    assert g.gap_m(angles['preopen']) == pytest.approx(.036, abs=1e-6)
    assert g.gap_m(angles['release']) == pytest.approx(.040, abs=1e-6)
    with pytest.raises(ValueError):
        g.angle_for_gap(.2)


def test_pad_boxes_mirror_each_other_and_sit_on_the_pad_face():
    (cx, cy, cz), size, angle = g.pad_box(1)
    assert g.pad_box(-1) == ((cx, -cy, cz), size, -angle)
    assert size == pytest.approx((g.PAD_THICKNESS_M, .017, .018))
    nx, ny = g.pad()['normal']
    # the box's inner face (toward the other jaw) lies in the mesh pad plane
    assert nx*cx+ny*cy-g.PAD_THICKNESS_M/2 == pytest.approx(g.pad()['offset'], abs=1e-9)


def test_pad_bottom_is_at_the_tcp_for_a_top_down_wrist():
    a = math.sqrt(.5)
    bottom = f.pad_sweep_bottom_relative_tcp([a, 0., a, 0.], g.GRIPPER)
    assert -.001 < bottom <= 0.  # the new TCP is the lower end of the pad
    assert f.pad_sweep_bottom_relative_tcp([a, 0., a, 0.]) != bottom  # stock jaw keeps its own sweep
    with pytest.raises(ValueError):
        f.pad_sweep_bottom_relative_tcp([a, 0., a, 0.], 'other')


def test_prepare_resolves_jaw_meshes_and_the_new_tcp(tmp_path):
    urdf = prepare('omx_f', tmp_path/'p.urdf', g.GRIPPER)
    root = ET.parse(urdf).getroot()
    assert root.find("joint[@name='end_effector_joint']/origin").get('xyz').split()[0] == '0.0740'
    def mesh_file(mesh):
        return Path(url2pathname(unquote(urlparse(mesh.get('filename')).path)))
    names = {mesh_file(m).name for m in root.iter('mesh')}
    assert {'palletizing_jaw6_servo_side_v2_1.stl', 'palletizing_jaw7_gear_side_v2_1.stl', 'follower_01_base.stl'} <= names
    assert all(mesh_file(m).is_file() for m in root.iter('mesh'))
    f.check_massless_tcp(urdf)
    stock = ET.parse(prepare('omx_f', tmp_path/'s.urdf')).getroot()
    assert stock.find("joint[@name='end_effector_joint']/origin").get('xyz').split()[0] == '0.09193'
    assert not any('palletizing' in m.get('filename') for m in stock.iter('mesh'))
    with pytest.raises(ValueError):
        prepare('omx_l', tmp_path/'l.urdf', g.GRIPPER)


def test_cases_are_opt_in_and_the_default_keeps_the_stock_jaw_and_60_g():
    base = f.container_fixture(layers=3, case='nominal')
    assert not {'gripper', 'tcp_offset_m', 'cargo_mass_kg', 'grasp_hold_check'} & set(base)
    value = f.container_fixture(layers=3, case=CASE)
    assert (value['gripper'], value['tcp_offset_m'], value['cargo_mass_kg']) == (g.GRIPPER, [.074, -.0016, 0.], [.0072, .01179, .016])
    assert 'grasp_hold_check' not in value and f.container_fixture(layers=3, case=HOLD)['grasp_hold_check'] is True
    assert json.loads(json.dumps(value)) == value  # the report verifier compares the fixture after a JSON round trip
    assert f.plan(True, fixture=value)[0]['mass'] == .016 and f.plan(True, fixture=base)[0]['mass'] == .06


def test_planner_uses_the_requested_tcp_only_when_asked(tmp_path):
    fixture = f.container_fixture(layers=3, case=CASE)

    def homes(**extra):
        case, out = tmp_path/'case.json', tmp_path/f'out-{len(list(tmp_path.glob("out-*")))}.json'
        case.write_text(json.dumps(dict(schema='rosy.omx-sim-stack-plan/1', operation='homes', bases=fixture['arm_bases_m'],
            base_yaws=fixture['arm_base_yaws_rad'], points=[f.home(i, True, fixture=fixture) for i in range(2)], **extra)))
        done = subprocess.run([sys.executable, str(f.ROOT/'deploy/robot/omx/isaac_stack_plan.py'), '--case', str(case),
                               '--out', str(out)], capture_output=True)
        return done, json.loads(out.read_text()) if done.returncode == 0 else None
    (_, stock), (_, short) = homes(), homes(tcp_x_m=.074)
    assert stock['homes'][0] != short['homes'][0]  # a shorter TCP puts the wrist further out
    assert homes(tcp_x_m=.5)[0].returncode != 0
