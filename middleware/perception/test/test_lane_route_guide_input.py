"""An authority-bound route prior cannot outlive its source or a clear."""

import json

from control.lane_route_guide_input import LaneRouteGuideInput


def message(seq=1, epoch="core-a", clear=False, **changes):
    guide = dict(leg_id="trip:rev1", authority_seq=3, map_id="map-a", map_revision=2,
                 source_stamp_s=10., valid_until_s=10.8, heading_here_deg=0.,
                 heading_ahead_deg=45., ahead_m=.25, s_m=.5, off_route_m=.01,
                 pivot_ok=False)
    guide.update(changes)
    return json.dumps(dict(v=1, publisher_epoch=epoch, seq=seq, guide=None if clear else guide))


def test_source_deadline_is_not_renewed_by_delivery_or_republication():
    inbox = LaneRouteGuideInput()
    inbox.receive(message(), 10.7)
    assert inbox.for_frame(10.75).heading_ahead_deg == 45.
    inbox.receive(message(seq=2), 10.79)
    assert inbox.for_frame(10.8) is None


def test_clear_rejects_late_active_messages():
    inbox = LaneRouteGuideInput()
    inbox.receive(message(), 10.1)
    inbox.receive(message(seq=3, clear=True), 10.2)
    inbox.receive(message(seq=2), 10.3)
    assert inbox.for_frame(10.3) is None


def test_new_publisher_requires_clear_and_retires_previous_epoch():
    inbox = LaneRouteGuideInput()
    inbox.receive(message(), 10.1)
    inbox.receive(message(epoch="core-b"), 10.2)
    assert inbox.for_frame(10.2) is None
    inbox.receive(message(seq=0, epoch="core-b", clear=True), 10.2)
    inbox.receive(message(seq=1, epoch="core-b"), 10.3)
    assert inbox.for_frame(10.3) is not None
    inbox.receive(message(seq=99, clear=True), 10.4)
    assert inbox.for_frame(10.4) is not None


def test_future_and_overlong_priors_do_not_supply_a_guide():
    for change in ({"source_stamp_s": 10.2}, {"valid_until_s": 13.1}, {"pivot_ok": True}):
        inbox = LaneRouteGuideInput()
        inbox.receive(message(**change), 10.1)
        assert inbox.for_frame(10.3) is None


def test_epoch_capacity_failure_cannot_revive_previous_publisher():
    inbox = LaneRouteGuideInput()
    for index in range(65):
        inbox.receive(message(seq=0, epoch=f"core-{index}", clear=True), 10.1)
    inbox.receive(message(seq=1, epoch="core-64"), 10.2)
    assert inbox.for_frame(10.2) is not None
    inbox.receive(message(seq=0, epoch="core-65", clear=True), 10.3)
    inbox.receive(message(seq=99, epoch="core-64"), 10.4)
    assert inbox.for_frame(10.4) is None


def test_paused_source_clock_does_not_extend_local_receipt_budget():
    now = [0.]
    inbox = LaneRouteGuideInput(clock=lambda: now[0])
    inbox.receive(message(), 10.1)
    now[0] = .6
    inbox.receive(message(seq=2), 10.1)
    now[0] = .71
    assert inbox.for_frame(10.1) is None


def test_short_preview_distance_is_retained_for_the_consumer():
    inbox = LaneRouteGuideInput()
    inbox.receive(message(ahead_m=.05), 10.1)
    assert inbox.for_frame(10.2).ahead_m == .05
