"""Native re-inference masks from failed NW corners, not original worker-state replay.

ONNX SHA256: 451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2.
PNG hashes identify the 320x240 inputs; packbits preserve every inferred way pixel.
Actual ground, camera offset and lane half are those used by the recorded run.
"""
import base64
import gzip
import json
import math
from pathlib import Path
import zlib

import numpy as np
import pytest

from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.drivable.drivable_steer import DrivableSteer, way_target
from control.sensing.perception.drivable.target import _centre_target


G = GroundPlane(.06343, .13962634015954636, 281.59681292203703, 160, 120, .6)
MASKS = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures' /
    'drivable_centre_row_order_20261020.json.gz').read_bytes()))['masks']


@pytest.fixture(params=[0, 1], ids=['e434-91s', '8812-92s'])
def case(request):
    return request.param


@pytest.fixture
def way(case):
    packed = zlib.decompress(base64.b64decode(MASKS[case]['way_packbits_zlib_b64']))
    assert len(packed) == 240 * 320 // 8
    return np.unpackbits(np.frombuffer(packed, np.uint8)).reshape(240, 320).astype(bool)


def test_far_normal_offsets_cannot_precede_the_near_observed_centre(way):
    info = way_target(way, G, .03317, .0925)
    x, y = info['target_m']
    assert x >= .18 and abs(math.degrees(math.atan2(y, x)) - 10.) < 30


def test_corrected_rows_preserve_the_selected_near_route_junction(way):
    pose = (0., 0., 0.)
    assert way_target(way, G, .03317, .0925)['exit_near']['right']
    error, confidence, info = DrivableSteer().update(way, 1., G, .03317, .0925, pose, pose,
        observed_only=True, current_stamp=1.125, guide_fresh=True,
        guide_here_deg=10., guide_deg=-75., guide_pivot_ok=False)
    assert info['strategy'] == 'drivable_turn_right' and error > 0
    assert not info.get('future_turn_deferred')
    assert confidence == .6


def test_confidence_uses_the_same_image_rows_as_the_reversed_target_input():
    way = np.zeros((240, 320), bool)
    way[150:200, :221] = True
    way[200:, 100:221] = True
    assert way_target(way, G, .03317, .0925, lookahead=.15)['both']


def test_a_continuous_bend_keeps_row_order_when_x_folds_after_ninety_degrees():
    distance = np.linspace(.001, .27, 100)
    radius = .12
    xs = radius * np.sin(distance / radius)
    ys = radius * (1. - np.cos(distance / radius))
    point, curvature, _ = _centre_target(xs, ys, .25)
    assert curvature == pytest.approx(1. / radius, abs=.2)
    assert point == pytest.approx((radius * math.sin(.25 / radius),
                                   radius * (1. - math.cos(.25 / radius))), abs=.005)
