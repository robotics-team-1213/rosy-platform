"""Opt-in navy stud plate (KAN-108 CAD): dot grid, no dot under a container, release floor."""
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f
import ship_plate as sp

CASE = 'nominal-palletizing-v21-ship'
TOP_DOWN = [math.sqrt(.5), 0., math.sqrt(.5), 0.]


def ship():
    return f.container_fixture(layers=3, case=CASE)


def test_case_is_opt_in_and_keeps_the_v21_jaw_and_mass():
    base, v21, value = (f.container_fixture(layers=3, case=c) for c in ('nominal', 'nominal-palletizing-v21', CASE))
    assert 'ship_plate' not in base and 'ship_plate' not in v21 and base['bin_origin_m'][2] == .074
    assert (value['gripper'], value['cargo_mass_kg']) == (v21['gripper'], v21['cargo_mass_kg'])
    assert json.loads(json.dumps(value)) == value  # the report verifier compares the fixture after a JSON round trip


def test_rows_sit_at_the_stud_pitch_on_the_plate_top():
    value = ship()
    assert value['bin_origin_m'][2] == pytest.approx(.072+.008)  # work table top plus the CAD plate thickness 8 mm
    targets = [i['target'] for i in f.plan(True, fixture=value)[:3]]
    assert [round(t[1], 5) for t in targets] == [0., -.036, .036]  # row pitch 36 mm: 30 mm box + 6 mm lane
    assert value['bin_size_m'][1] == pytest.approx(3*.036-.006)
    assert all(t[2] == pytest.approx(value['bin_origin_m'][2]+.015) for t in targets)


def test_studs_are_a_6_by_6_grid_inside_the_outline_and_none_is_under_a_container():
    value = ship()
    spec, studs = value['ship_plate'], sp.stud_positions(value)
    assert len(studs) == 36 and {round(y, 5) for _, y in studs} == {round(sp.stack_centre(value)[1]+(k-2.5)*.036, 5) for k in range(6)}
    xs = sorted({round(x, 5) for x, _ in studs})
    assert all(b-a == pytest.approx(.036, abs=1e-5) for a, b in zip(xs, xs[1:]))
    polygon, r = sp.outline(value), spec['stud_diameter_m']/2
    for x, y in studs:  # inside the convex outline, counter-clockwise
        for (ax, ay), (bx, by) in zip(polygon, polygon[1:]+polygon[:1]):
            assert ((bx-ax)*(y-ay)-(by-ay)*(x-ax))/math.hypot(bx-ax, by-ay) > r
    for item in f.plan(True, fixture=value):
        (cx, cy), (hx, hy) = item['target'][:2], (item['size'][0]/2, item['size'][1]/2)
        for x, y in studs:
            assert abs(x-cx) > hx+r or abs(y-cy) > hy+r  # the stud disc does not touch the body footprint
    nearest = min(abs(abs(y-sp.stack_centre(value)[1])-.015-r) for _, y in studs if abs(y-sp.stack_centre(value)[1]) < .02)
    assert nearest == pytest.approx(.0004, abs=1e-6)  # 0.4 mm between a box side and the dot beside it (drawing: 0.41)


def test_mesh_has_a_triangle_for_every_vertex_reference_and_studs_stand_3_mm_over_the_plate():
    value = ship()
    points, tris, plate = sp.mesh(value)
    assert max(i for t in tris for i in t) == len(points)-1 and plate == 20
    spec = value['ship_plate']
    assert (spec['pitch_m'], spec['stud_diameter_m'], spec['thickness_m']) == (.036, .0052, .008) and spec['source']['issue'] == 'KAN-108'
    top = sp.top_z(value)
    assert max(p[2] for p in points) == pytest.approx(top+.003) and min(p[2] for p in points) == pytest.approx(.072)  # the plate underside is the work table top


def test_release_floor_keeps_box_and_finger_above_the_studs():
    value, top = ship(), sp.top_z(ship())
    stud_top = top+.003+.001
    assert sp.release_floor_z(value, .0016) == pytest.approx(stud_top+.015)  # pad above the box centre: the box bottom binds
    assert sp.release_floor_z(value, -.02) == pytest.approx(stud_top+.02)  # a finger 20 mm below the centre binds instead
    assert sp.finger_clearance_m(value, stud_top) == pytest.approx(.001)


def sample(box_z, tcp_z):
    boxes = [dict(position=[.08, 0., box_z], orientation=[1., 0., 0., 0.]) for _ in range(9)]
    return dict(boxes=boxes, tcps=[[0., 0., tcp_z]]*2, wrist_orientations=[TOP_DOWN]*2)


def test_first_layer_release_never_goes_below_the_floor_and_other_cases_are_unchanged():
    value = ship()
    target = f.plan(True, fixture=value)[0]['target'][2]
    low = dict(value, stack_release_clearance_m=0.)  # a release at the plate top would put the box bottom on the studs
    z = f.packed_release_position(0, sample(target+.02, target+.022), low)[2]
    assert z == pytest.approx(sp.release_floor_z(value, .022-.02-.0005), abs=1e-3) and z >= target+.004-1e-9
    assert f.packed_release_position(0, sample(target+.02, target+.022), value)[2] == pytest.approx(target+.005)
    v21 = f.container_fixture(layers=3, case='nominal-palletizing-v21')
    assert f.packed_release_position(0, sample(.1, .102), v21)[2] == pytest.approx(f.plan(True, fixture=v21)[0]['target'][2]+.015)


def test_plate_stays_on_the_table_and_off_the_leveling_spot():
    value = ship()
    xs = [x for x, _ in sp.outline(value)]
    assert max(xs) <= .155 and min(xs) > value['leveling_center_m'][0]+.045  # stern on the table (cropped to 16 mm behind the first row); the leveled 90 mm box clears the bow
    assert max(x for x, _ in sp.stud_positions(value)) == pytest.approx(.08+1.5*.036)  # first row = the container end lane
    polygon = sp.outline(value)
    assert max(x for x, _ in polygon) == pytest.approx(.08+1.5*.036+.016) and min(x for x, _ in polygon) == pytest.approx(.134-.198)  # stern 16 mm behind the first row, bulwark at 198


def test_free_channels_flank_the_stack_one_per_arm():
    value = ship()
    channels = sp.free_channels(value)
    assert [c['y_m'] for c in channels.values()] == [-.072, .072] and channels[0]['clear_width_m'] == pytest.approx(.0308)
    stack = {i['target'][1] for i in f.plan(True, fixture=value)}
    assert all(abs(abs(c['y_m'])-.036-.015) > .02 for c in channels.values()) and max(stack) == pytest.approx(.036)
    assert len(channels[0]['x_cells_m']) == 5


def test_ship_case_opens_the_jaw_only_to_33_mm():
    import palletizing_gripper as g
    value = ship()
    assert value['release_gap_m'] == .033 and 'release_gap_m' not in f.container_fixture(layers=3, case='nominal-palletizing-v21')
    assert g.gap_m(g.finger_angles(.033)['release']) == pytest.approx(.033, abs=1e-5)
    assert g.finger_angles()['release'] > g.finger_angles(.033)['release']


def test_a_box_resting_on_a_stud_is_not_seated_on_the_plate_only():
    from test_container_stack import bodies
    value_ship, flat = ship(), f.container_fixture(layers=3, case='nominal-palletizing-v21')
    for value, seated_when_high in ((value_ship, False), (flat, True)):
        box = bodies(value)[0]
        assert f.stable_box(box, 0, True, fixture=value)
        box['position'][2] += .001  # Isaac y040 run: first-layer box 1.0 mm high on a stud
        assert f.stable_box(box, 0, True, fixture=value) is seated_when_high
