"""Keep refuses to drive on when the map says the body is off the route's road (g8-9dfk, 2026-10-10)."""
import json
from types import SimpleNamespace

import numpy as np

from control.sensing.perception.drivable.drivable_keep import keep_step, parse_guide
from control.sensing.perception.drivable.drivable_steer import DrivableSteer


def test_off_route_guide_holds_before_the_camera_way_is_used():
    guide = parse_guide(json.dumps(dict(heading_ahead_deg=10.0, stamp=5.0, off_route_m=0.2)), 5.0)
    assert guide[4] == 0.2
    worker = SimpleNamespace(used_crosswalk=None, latest_way=lambda _age: (np.ones((240, 320), bool), 5.0))
    last = {}
    result, decided = keep_step(DrivableSteer(), worker, last, None, 0.033, 0.0925,
                                lambda _t: (0.0, 0.0, 0.0), 5.0, None, guide)
    assert result is None and decided and last['reason'] == 'off_route_hold'
    assert parse_guide(json.dumps(dict(heading_ahead_deg=10.0)), 1.0)[4] is None
