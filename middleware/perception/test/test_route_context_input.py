"""D-531 CORE route context is an expiring hint for camera evidence."""

import json
import numpy as np

from control.route_context_input import RouteContextInput, bend_expected
from control.sensing.perception.lane_keep import LaneKeeper
from test_lane_keep_bend import CAMERA_X, HALF, FIXTURE, _ground


def _context(**changes):
    value = dict(v=1, seq=7, place_id="bend-1", map_id="floor-1",
                 stamp_s=10.0, valid_until_s=10.8, kind="bend", ahead_m=[0.2, 0.4],
                 lane_turn_deg=30.0)
    value.update(changes)
    return json.dumps(value)


def test_valid_bend_context_applies_only_in_lead_window():
    inbox = RouteContextInput()
    inbox.receive(_context())
    context = inbox.for_frame(10.3)
    assert context.seq == 7 and bend_expected(context)
    inbox.receive(_context(ahead_m=[0.71, 0.8]))
    assert not bend_expected(inbox.for_frame(10.3))
    inbox.receive(_context(kind="junction", ahead_m=[0.2, 0.4]))
    assert not bend_expected(inbox.for_frame(10.3))


def test_future_stale_and_expired_context_never_applies():
    inbox = RouteContextInput()
    inbox.receive(_context())
    assert inbox.for_frame(9.89) is None
    inbox.receive(_context())
    assert inbox.for_frame(9.90) is not None
    assert inbox.for_frame(10.5) is not None
    assert inbox.for_frame(10.501) is None
    inbox.receive(_context())
    assert inbox.for_frame(10.801) is None


def test_clear_and_bad_messages_revoke_previous_context():
    inbox = RouteContextInput()
    inbox.receive(_context())
    inbox.receive('{"v": 1, "seq": null}')
    assert inbox.for_frame(10.1) is None
    inbox.receive(_context())
    inbox.receive(_context(ahead_m=[-1, 4]))
    assert inbox.for_frame(10.1) is None
    inbox.receive(_context())
    inbox.receive('{broken')
    assert inbox.for_frame(10.1) is None


def test_clock_reset_does_not_reuse_old_context():
    inbox = RouteContextInput()
    inbox.receive(_context())
    assert inbox.for_frame(0.0) is None
    assert inbox.for_frame(10.1) is None


def test_stale_context_does_not_revive_for_a_late_old_frame():
    inbox = RouteContextInput()
    inbox.receive(_context())
    assert inbox.for_frame(10.6) is None
    assert inbox.for_frame(10.3) is None


def test_recorded_bend_clip_uses_route_context_then_returns_to_plain_keeper():
    data = np.load(FIXTURE)
    frames = [frame for frame, meta in zip(data['frames'], json.loads(str(data['meta'])))
              if meta['clip'] == 'bend_fork']
    inbox = RouteContextInput()
    inbox.receive(_context())
    guided = LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True)
    explicit = LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True)
    ground = _ground()
    for i, frame in enumerate(frames):
        expected = bend_expected(inbox.for_frame(10.0 + i * 0.04))
        guided.update(frame, ground, lane_half_width_m=HALF, bend_expected=expected)
        explicit.update(frame, ground, lane_half_width_m=HALF, bend_expected=True)
        assert guided.last['strategy'] == explicit.last['strategy']
        assert guided.last.get('reason') == explicit.last.get('reason')
    inbox.receive('{"v": 1, "seq": null}')
    assert not bend_expected(inbox.for_frame(10.45))
