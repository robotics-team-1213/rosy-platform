"""The arm S Isaac cell reproduces the real failures and judges only what the box and the arm did."""
import importlib
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
f = importlib.import_module('arm_s_cell_fixture')


def test_the_box_starts_on_the_tray_and_the_overhang_place_puts_its_edge_over_the_frame():
    (x, y, z), yaw = f.box_start('nominal')
    assert z == f.TRAY['top'] + f.BOX / 2 and yaw == f.BOX_YAW_DEG  # square to the jaws, as on the real tray
    px, py, _ = f.place_point('overhang')
    frame_near_edge = f.FRAME['center'][1] - f.FRAME['size'][1] / 2
    assert py + f.BOX / 2 > frame_near_edge and py < frame_near_edge  # centre on the tray, edge over the frame
    assert f.place_point('nominal')[:2] == f.BELT['center'] and f.box_start('wrong-yaw')[1] == f.BOX_YAW_DEG + 20.


def sample(tick, phase, box, frame=0., error=.001):
    return dict(tick=tick, phase=phase, box_position=list(box), frame_contact_n=frame, joint_error_rad=error)


def test_a_turned_box_carried_but_set_down_off_the_point_is_held_not_placed():
    off = (f.BELT['center'][0] + .02, f.BELT['center'][1] - .01, f.BELT['top'] + f.BOX / 2)
    samples = [sample(4, 'grasp', (.072, .106, f.TRAY['top'] + .02)), sample(8, 'transfer', (.11, .05, .12)),
               sample(12, 'release', off)]
    judged = f.evaluate(samples, 'wrong-yaw')
    assert judged['result'] == 'held_not_placed' and not judged['matches_expectation']


def test_a_box_set_down_on_the_belt_is_placed():
    top = f.BELT['top'] + f.BOX / 2
    samples = [sample(4, 'approach', (.072, .106, f.TRAY['top'] + .02)), sample(8, 'transfer', (.11, .05, .12)),
               sample(12, 'release', (*f.BELT['center'], top))]
    judged = f.evaluate(samples, 'nominal')
    assert judged['result'] == 'placed' and judged['matches_expectation'] and judged['first_soft_contact_tick'] is None


def test_a_touch_on_the_frame_and_the_arm_lag_it_causes_are_reported():
    samples = [sample(4, 'transfer', (.072, .121, .10)),
               sample(8, 'descend_place', (.072, .121, .07), frame=.4, error=math.radians(4))]
    judged = f.evaluate(samples, 'overhang')
    assert judged['result'] == 'frame_contact' and judged['matches_expectation'] is True
    assert judged['first_soft_contact_tick'] == 8  # where the real runner would have held with torque on


def test_a_box_never_lifted_was_not_held():
    still = (.072, .106, f.TRAY['top'] + f.BOX / 2)
    judged = f.evaluate([sample(4, 'grasp', still, error=math.radians(5)), sample(8, 'transfer', still)], 'wrong-yaw')
    assert judged['result'] == 'not_held' and judged['matches_expectation']
    assert judged['first_soft_contact_tick'] == 4  # the grasp pushed a joint past the soft-contact bound
