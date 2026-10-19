"""Correct a known non-way source arc only with a witnessed same-band alternative."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.drivable.drivable_steer import DrivableSteer, way_target
from test_drivable_exit_admission import G, POSE


def recorded_way():
    doc = json.loads((Path(__file__).parent / 'fixtures' /
        'drivable_arc_support_20261020.json').read_text())
    way = np.zeros(doc['shape'], bool)
    for row, runs in enumerate(doc['way_runs']):
        for start, end in runs:
            way[row, start:end] = True
    assert hashlib.sha256(np.packbits(way).tobytes()).hexdigest() == doc['packbits_sha256']
    return way


def test_recorded_open_corridor_replaces_the_non_way_path_arc_with_its_supported_chord():
    info = way_target(recorded_way(), G, .03317, .0925)
    assert info['ahead_m'] >= .6
    assert info['curvature_1pm'] == pytest.approx(-.997, abs=.001)
    assert info['target_m'][0] > .24 and -.04 < info['target_m'][1] < 0.


def test_the_corrected_target_clears_the_existing_realign_gate_even_with_previous_smoothing(monkeypatch):
    import control.sensing.perception.drivable.drivable_steer as module
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    owner, way, clock = DrivableSteer(), recorded_way(), [0.]
    owner._smoothed = -4.8
    for i in range(25):
        clock[0] = i / 8
        error, _, info = owner.update(way, i / 8, G, .03317, .0925, POSE, POSE,
            guide_here_deg=1.4066, guide_deg=1.4066, observed_only=True, current_stamp=i / 8 + .125)
        assert error is not None and info.get('reason') != 'realign'


def test_visible_non_way_pixels_between_samples_are_not_skipped():
    from control.sensing.perception.drivable.target import _arc_floor
    way = np.ones((10, 10), bool)
    ground = GroundPlane(.0000495, 0., 1000., 5., 5., 1.)
    assert _arc_floor(way, ground, 0., 0., .25) is True
    way[8, 5] = False  # the first two visible samples round to rows 9 and 7
    assert _arc_floor(way, ground, 0., 0., .25) is False


def test_unknown_offscreen_is_not_a_supported_alternative():
    from control.sensing.perception.drivable.target import _arc_floor
    assert _arc_floor(np.ones((240, 320), bool), G, .03317, 0., .05) is None


def test_a_supported_bend_keeps_the_existing_path_curvature():
    from control.sensing.perception.drivable.target import _arc_floor, _centre_target, _col_y, _observed_target, _row_x
    xs, ys = list(np.linspace(.04, .16, 7)), [0.] * 7
    for distance in np.linspace(.02, .12, 6):
        xs.append(.16 + .2 * math.sin(distance / .2))
        ys.append(.2 * (1. - math.cos(distance / .2)))
    xs, ys = np.asarray(xs), np.asarray(ys)
    rows, cols = np.indices((240, 320))
    x = _row_x(rows[:, 0], G, .03317)[:, None]
    y = _col_y(cols, rows, G)
    centre = np.where(x <= .16, 0., .2 - np.sqrt(np.maximum(0., .04 - (x - .16) ** 2)))
    way = (x < .33) & (np.abs(y - centre) < .06)
    choice = _centre_target(xs, ys, .25)
    assert choice[1] > 1.2 and _arc_floor(way, G, .03317, choice[1], .25) is True
    assert _observed_target(choice, xs, ys, .25, way, G, .03317) is choice


@pytest.mark.parametrize('fill', [False, True])
def test_no_unverified_fallback_is_created_when_the_correction_conditions_are_absent(fill):
    from control.sensing.perception.drivable.target import _observed_target
    choice = ((.194, -.133), -4.8, np.ones(2, bool))
    xs, ys = np.array([.2, .24]), np.array([-.02, -.03])
    assert _observed_target(choice, xs, ys, .25, np.full((240, 320), fill, bool), G, .03317) is choice
