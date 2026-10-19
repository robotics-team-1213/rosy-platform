"""Near admission and target must refer to one connected frame-border opening."""
import hashlib
import json
from pathlib import Path

import numpy as np

from control.sensing.perception.drivable.drivable_steer import DrivableSteer, way_target
from test_drivable_exit_admission import G, POSE


def test_recorded_disconnected_openings_keep_the_near_target_and_memory():
    # Native PNG1356: five near rows and six separate far rows were pooled.
    doc = json.loads((Path(__file__).parent / 'fixtures' /
        'drivable_disconnected_exit_20261020.json').read_text())
    way = np.zeros(doc['shape'], bool)
    for row, runs in enumerate(doc['way_runs']):
        for start, end in runs:
            way[row, start:end] = True
    assert hashlib.sha256(np.packbits(way).tobytes()).hexdigest() == doc['packbits_sha256']
    raw = way_target(way, G, .03317, .0925)
    assert raw['exit_near']['right']
    assert raw['exit_point_m']['right'][0] < .2 and raw['exit_reach_m']['right'] < .2
    owner = DrivableSteer()
    error, _, info = owner.update(way, 1., G, .03317, .0925, POSE, POSE,
        guide_here_deg=33., guide_deg=-55., observed_only=True, current_stamp=1.125)
    assert error > 0 and info['strategy'] == 'drivable_turn_right'
    assert owner._route_exit[1] == raw['exit_point_m']['right']


def border():
    xs = np.array([.45, .44, .43, .42, .41, .40, .30, .25, .188, .186, .184, .182, .139])
    rows = np.arange(len(xs))
    edge = np.array([True] * 6 + [False] * 2 + [True] * 4 + [False])
    return xs, rows, edge


def test_two_valid_openings_do_not_share_reach_or_target_rows():
    from control.sensing.perception.drivable.target import _exit_rows
    xs, rows, edge = border()
    chosen, near = _exit_rows(xs, rows, edge, 4, .05)
    assert near and chosen.tolist() == [8, 9, 10, 11]


def test_an_isolated_near_hit_cannot_admit_a_separate_far_opening():
    from control.sensing.perception.drivable.target import _exit_rows
    xs, rows, edge = border()
    edge[9:12] = False
    chosen, near = _exit_rows(xs, rows, edge, 4, .05)
    assert not near and chosen.tolist() == list(range(6))


def test_missing_image_rows_split_an_opening_even_when_ranges_are_close():
    from control.sensing.perception.drivable.target import _exit_rows
    xs, rows, edge = border()
    rows[10:] += 3
    chosen, near = _exit_rows(xs, rows, edge, 4, .05)
    assert not near and chosen.tolist() == list(range(6))


def test_a_wide_connected_opening_keeps_its_full_observed_extent():
    from control.sensing.perception.drivable.target import _exit_rows
    xs, rows, edge = border()
    edge[:12] = True
    chosen, near = _exit_rows(xs, rows, edge, 4, .05)
    assert near and chosen.tolist() == list(range(12))
    assert xs[chosen].max() == .45
