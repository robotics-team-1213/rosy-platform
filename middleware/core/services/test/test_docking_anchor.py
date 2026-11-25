"""The seat anchor: "seated in bay X now" as an odom-bound pair for Fleet (dock_anchor.py)."""

from __future__ import annotations

import math
import pytest

from core_common.protocol.localization import OdomPose
from core_features.docking.bay_scan_pose import BayScanPose
from core_features.docking.dock_anchor import DockAnchorKeeper
from core_features.docking.model import DockingConfig
from core_common.protocol.schemas import DockState
from test_docking_bay_scan_pose import answer_kinds, good, with_reference
from test_docking_bay_zone import a_row, run_row

WALL = 1000.0


def _fixed_odom(manager, epoch=3, age=0.2):
    """Odom the manager's keeper pairs: x 1.0 y 2.0 yaw 0.3, stamped age seconds before the keeper's wall clock."""
    state = {"epoch": epoch, "age": age}
    manager._anchor._wall = lambda: WALL
    manager._anchor._odom = lambda: OdomPose(x=1.0, y=2.0, yaw=0.3, stamp=WALL - state["age"], epoch=state["epoch"], mono_s=5.0)
    return state


def _docked_seat(charges, battery=100.0, seat=None):
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=charges)
    with_reference(p)
    p.battery.percent = battery
    odom = _fixed_odom(p.manager)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=seat if seat is not None else good(x=0.01, heading=math.radians(2.0))))
    return p, odom


def test_a_lidar_confirmed_seat_emits_the_anchor_with_the_odom_pair_and_the_seat_error():
    p, odom = _docked_seat(charges=False)
    assert p.manager.state is DockState.DOCKED
    anchor = p.manager.status().anchor
    assert anchor is not None and anchor.dock_id == "bay1" and anchor.confirmation == "lidar_reference" and anchor.source == "docked"
    assert (anchor.odom_pose.x, anchor.odom_pose.y, anchor.odom_pose.yaw, anchor.odom_pose.epoch) == (1.0, 2.0, 0.3, 3)
    assert abs(anchor.along_m - 0.01) < 1e-6 and abs(anchor.heading_deg - 2.0) < 1e-6 and anchor.inliers == 0.95 and anchor.age_s == 0.0
    sent = [d for t, d in p.events if t == "docking.anchor"]
    assert len(sent) == 1 and sent[0]["odom_epoch"] == 3 and sent[0]["confirmation"] == "lidar_reference" and sent[0]["source"] == "docked"


def test_a_charge_contact_dock_with_a_failed_seat_scan_publishes_no_anchor_but_is_still_docked():
    p, odom = _docked_seat(charges=True, battery=60.0, seat=good(inliers=0.3))      # the seat scan does not fit: the voltage rise on the contact docks it
    assert p.manager.state is DockState.DOCKED
    assert p.manager.status().anchor is None and not [t for t, d in p.events if t == "docking.anchor"]     # it could name the wrong bay


def test_the_anchor_is_hidden_once_its_odom_epoch_ended_and_there_is_none_without_a_fresh_odom():
    p, odom = _docked_seat(charges=False)
    assert p.manager.status().anchor is not None
    odom["epoch"] = 4                                                     # a CORE restart / an odom discontinuity: the odom frame of the pair no longer exists
    assert p.manager.status().anchor is None
    q, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(q)
    q.battery.percent = 100.0
    _fixed_odom(q.manager, age=5.0)                                       # the odom is 5 s old: nothing to pair with
    q.manager.dock()
    run_row(q, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01, heading=math.radians(2.0))))
    assert q.manager.state is DockState.DOCKED and q.manager.status().anchor is None


def test_no_anchor_when_the_robot_moved_between_the_seat_scan_and_docked():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.battery.percent = 100.0
    _fixed_odom(p.manager)
    p.manager.dock()
    bp = p.manager._bay_phases
    orig = bp.seat_anchor_evidence

    def moved():
        bp._seat_odom = (bp._seat_odom[0] + 0.01, bp._seat_odom[1], bp._seat_odom[2])      # the wheels were 1 cm elsewhere at the seat scan: it did not stand still
        return orig()
    bp.seat_anchor_evidence = moved
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01, heading=math.radians(2.0))))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None


def test_an_anchor_failure_never_blocks_docked():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    p.battery.percent = 100.0
    _fixed_odom(p.manager)

    def boom(*args, **kwargs):
        raise RuntimeError("anchor store broke")
    p.manager._anchor.record = boom
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01, heading=math.radians(2.0))))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None


def test_the_snapshot_carries_the_anchor_for_polling_keyed_by_dock_epoch_and_at():
    from core_features.state.manager import StateManager  # noqa: PLC0415
    p, odom = _docked_seat(charges=False)
    state = StateManager("robot-1", stale_after_s={}, sources_configured=False)
    state.set_docking(p.manager.status())                                 # what docking_mode.tick does every cycle
    anchor = state.snapshot().docking.anchor
    assert anchor is not None and (anchor.dock_id, anchor.odom_pose.epoch, anchor.at) == ("bay1", 3, WALL)


def _keeper(events, odom, docks=("bay1",)):
    cfg = DockingConfig()
    t = {"now": 0.0}
    docks = [type("D", (), {"id": d, "metadata": {"reference_scan": {"ranges": [1.0]}}})() for d in docks]
    keeper = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: events.append((ty, data)), wall=lambda: WALL, mono=lambda: t["now"],
                              reference_provider=lambda: {d.id: d.metadata["reference_scan"] for d in docks})
    return keeper, t, docks


def _pose(x=1.0, epoch=2):
    return OdomPose(x=x, y=0.0, yaw=0.0, stamp=WALL - 0.1, epoch=epoch, mono_s=1.0)


def _seat(**over):
    args = dict(x=0.004, y=0.002, heading=math.radians(1.0), inliers=0.95, margin=0.6, median_m=0.002)
    args.update(over)
    return BayScanPose(**args)


def _still_frames(request, t, *, lag=0.0):
    """Keep sending frames throughout the configured 2 s of observed stillness."""
    start = t["now"]
    for k in range(8):
        t["now"] = start + k / 4
        assert request(0.0) is None
    t["now"] = start + 2
    return request(lag)


def test_the_startup_probe_asks_only_after_the_robot_stood_still_and_accepts_a_seat_fit():
    events, odom = [], {"pose": _pose()}
    keeper, t, docks = _keeper(events, odom)
    request = _still_frames(lambda lag: keeper.probe_request(True, docks, lag), t)
    assert request is not None and set(request[1]) == {"bay1"}
    anchor = keeper.note_probe_match({"bay1": _seat()}, request[0])
    assert anchor is not None and anchor.source == "startup_probe" and anchor.confirmation == "lidar_reference" and anchor.odom_pose.epoch == 2
    assert [e for e in events if e[0] == "docking.anchor"][0][1]["source"] == "startup_probe"
    t["now"] = 30.0
    assert keeper.probe_request(True, docks) is None                     # done: one anchor per run until the next record


def test_the_probe_refuses_a_weak_or_off_seat_fit_or_a_robot_that_moved_and_is_bounded_per_bay():
    for bad in (_seat(inliers=0.65), _seat(margin=0.2), _seat(x=0.05), _seat(y=0.04), _seat(heading=0.2), None):
        events, odom = [], {"pose": _pose()}
        keeper, t, docks = _keeper(events, odom)
        request = _still_frames(lambda lag: keeper.probe_request(True, docks, lag), t)
        assert request is not None and keeper.note_probe_match({"bay1": bad}, request[0]) is None and not events
    events, odom = [], {"pose": _pose()}
    keeper, t, docks = _keeper(events, odom)
    request = _still_frames(lambda lag: keeper.probe_request(True, docks, lag), t)
    odom["pose"] = _pose(x=1.02)                                          # it moved 2 cm while the scan was matched
    assert keeper.note_probe_match({"bay1": _seat()}, request[0]) is None
    t["now"] = 10.0
    keeper.probe_request(True, docks)                                     # the still timer restarted: no new request at once
    for k in range(40):                                                   # at most anchor_probe_tries (2) scans per bay, and not after the window
        t["now"] = 20.0 + k * 4.0
        keeper.probe_request(True, docks)
    assert keeper._tries["bay1"] <= DockingConfig().anchor_probe_tries
    assert keeper.probe_request(True, docks) is None


def test_no_probe_while_docking_or_estopped_and_a_stale_answer_is_dropped():
    from test_docking_bay import a_bay  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    t = {"now": 0.0}
    p.manager._anchor._odom = lambda: _pose()                             # an odom provider: the robot stands still
    p.manager._anchor._wall = lambda: WALL
    p.manager._anchor._mono = lambda: t["now"]
    request = _still_frames(p.manager.anchor_probe_request, t)
    assert request is not None and set(request[1]) == {"bay1"}
    t["now"] = 10.0
    p.safety.estop = True
    assert p.manager.anchor_probe_request() is None                       # an e-stopped robot is not probed
    p.safety.estop = False
    p.manager._state = DockState.DOCKING
    assert p.manager.anchor_probe_request() is None                       # nor while docking
    events, odom = [], {"pose": _pose()}
    keeper, t2, docks = _keeper(events, odom)
    assert keeper.note_probe_match({"bay1": _seat()}, 99) is None         # no open request
    assert keeper.probe_request(False, docks) is None


def test_the_probe_runs_through_the_bridge_for_an_idle_manager_and_never_breaks_the_scan_path(monkeypatch):
    import time  # noqa: PLC0415
    from core.bridge.observation import bay_body_scan  # noqa: PLC0415
    from core_features.docking import bay_scan_pose  # noqa: PLC0415
    from test_docking_bay import a_bay  # noqa: PLC0415
    from test_docking_bay_wiring import _open_scan, _services  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    t = {"now": 0.0}
    p.manager._anchor._odom = lambda: OdomPose(x=1.0, y=2.0, yaw=0.3, stamp=WALL - 0.1, epoch=3, mono_s=t["now"])
    from core_features.state.manager import StateManager
    state = StateManager("p", clock=lambda: WALL, monotonic=lambda: t["now"])
    p.manager._anchor._odom = state.odom_pose_record
    p.manager._anchor._history = state.odom_window_from
    p.manager._anchor._wall = lambda: WALL
    p.manager._anchor._mono = lambda: t["now"]
    monkeypatch.setattr(bay_scan_pose, "locate", lambda ref, live: BayScanPose(x=0.004, y=0.002, heading=0.01, inliers=0.95, margin=0.6, median_m=0.002))
    services = _services(p.manager)
    assert p.manager.body_scan_rear_overhang() is None                    # no dock active: the old early return
    for now in (k / 4 for k in range(9)):
        t["now"] = now
        scan = dict(_open_scan(), source_stamp_ns=1_000_000_000 + int(now * 1e9), source_now_ns=1_000_000_000 + int(now * 1e9))
        state.set_odom_pose(1.0, 2.0, 0.3, "odom", scan["source_stamp_ns"])
        bay_body_scan(services, scan, received_at=p.clock.now)
    for _ in range(100):
        if p.manager.status().anchor is not None:
            break
        time.sleep(0.02)
    anchor = p.manager.status().anchor
    assert anchor is not None and anchor.source == "startup_probe" and anchor.dock_id == "bay1"
    # the probe is wrapped: a raising manager method must not break the front-clearance path
    q = a_bay()
    q.manager.dock()
    q.manager.anchor_probe_request = lambda *args: (_ for _ in ()).throw(RuntimeError("probe broke"))
    bay_body_scan(_services(q.manager), _open_scan(), received_at=q.clock.now)
    assert q.manager._bay_phases._body is not None

def test_the_anchor_is_stamped_with_the_map_generation_when_the_core_has_one():
    events, odom = [], {"pose": _pose()}
    cfg = DockingConfig()
    keeper = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: events.append((ty, data)), wall=lambda: WALL,
                              map_generation_provider=lambda: 1234)
    seat = {"along_m": 0.001, "lateral_m": 0.0, "heading_deg": 0.5, "inliers": 0.95, "margin": 0.6}
    assert keeper.record("bay1", "docked", seat, keeper.observe()).map_generation == 1234
    plain = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: None, wall=lambda: WALL)
    assert plain.record("bay1", "docked", seat, plain.observe()).map_generation is None


@pytest.mark.parametrize("docks", [("C1", "C2"), ("C2", "C1")])
@pytest.mark.parametrize("other,expected", [(_seat(), None), (None, None), (_seat(x=math.nan), None), (_seat(x=0.12), "C1")])
def test_a_startup_anchor_requires_one_distinguishable_bay_on_the_same_frame(docks, other, expected):
    events = []
    keeper, t, candidates = _keeper(events, {"pose": _pose()}, docks)
    request_id, refs = _still_frames(lambda lag: keeper.probe_request(True, candidates, lag), t)
    assert set(refs) == {"C1", "C2"}
    anchor = keeper.note_probe_match({"C1": _seat(), "C2": other}, request_id)
    assert (anchor.dock_id if anchor else None) == expected
    assert len(events) == int(expected is not None)


@pytest.mark.parametrize("change", ["epoch", "transport_delay", "worker_delay", "movement", "disabled"])
def test_an_old_or_displaced_probe_cannot_name_a_bay(change):
    events, odom = [], {"pose": _pose()}
    keeper, t, docks = _keeper(events, odom)
    request = _still_frames(lambda lag: keeper.probe_request(True, docks, lag), t, lag=8.0 if change == "transport_delay" else 0.0)
    if change == "transport_delay":
        assert request is None
        return
    if change == "epoch":
        odom["pose"] = _pose(epoch=8)
    if change == "worker_delay":
        t["now"] += 8.0
    if change == "movement":
        odom["pose"] = _pose(x=1.011)
    if change == "disabled":
        keeper.probe_request(False, [])
    assert keeper.note_probe_match({"bay1": _seat()}, request[0]) is None
    assert not events


def test_a_seat_without_independent_identity_evidence_cannot_anchor_a_docked_robot():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    _fixed_odom(p.manager)
    p.battery.percent = 100.0
    p.manager.dock()
    accept = p.manager.note_bay_scan_match
    compare = p.manager.note_bay_seat_matches
    p.manager.note_bay_seat_matches = lambda matches, rid: compare({"bay1": good(x=0.01, margin=0.17)}, rid)

    def weak_alias(match, *args, **kwargs):
        if p.manager._bay_phases._req_kind == "seat":
            if not p.manager._bay_phases._req_track:
                match = good(x=0.01, margin=0.17)
        accept(match, *args, **kwargs)

    p.manager.note_bay_scan_match = weak_alias
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01)))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None
    assert not any(kind == "docking.anchor" for kind, data in p.events)


@pytest.mark.parametrize("change", ["worker_delay", "epoch", "position"])
def test_docked_does_not_publish_a_new_anchor_when_pose_changes_while_matching(change):
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    odom = _fixed_odom(p.manager)
    now = [0.0]
    p.manager._anchor._mono = lambda: now[0]
    p.battery.percent = 100.0
    p.manager.dock()
    accept = p.manager.note_bay_scan_match

    def delayed(match, *args, **kwargs):
        if p.manager._bay_phases._req_kind == "seat":
            if change == "worker_delay":
                now[0] += 8.0
            elif change == "epoch":
                odom["epoch"] += 1
            else:
                provider = p.manager._anchor._odom
                pose = provider()
                p.manager._anchor._odom = lambda: pose.model_copy(update={"x": pose.x + 0.011})
        accept(match, *args, **kwargs)

    p.manager.note_bay_scan_match = delayed
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01)))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None
    assert not any(kind == "docking.anchor" for kind, data in p.events)


@pytest.mark.parametrize("change", ["stationary", "reset", "excursion", "gap", "unbracketed"])
def test_delayed_lidar_is_bound_to_the_recorded_odom_on_both_sides_of_acquisition(change):
    from core_features.state.manager import StateManager
    t = {"now": 0.0}
    state = StateManager("p", clock=lambda: WALL + t["now"], monotonic=lambda: t["now"])
    keeper = DockAnchorKeeper(DockingConfig(), state.odom_pose_record, lambda: None, lambda *args: None,
                              wall=lambda: WALL + t["now"], mono=lambda: t["now"], odom_window_provider=state.odom_window_from)
    def write(seconds, *, x=0.0, frame="old"):
        t["now"] = seconds
        state.set_odom_pose(x, 0.0, 0.0, frame, 1_000_000_000 + round(seconds * 1e9))

    write(0)
    if change != "gap":
        write(0.7)
    write(0.9, x=0.011 if change == "excursion" else 0, frame="new" if change == "reset" else "old")
    stamp = 1_800_000_000
    if change == "unbracketed":
        stamp = 1_950_000_000
    t["now"] = 1
    observation = keeper.observe((2_000_000_000 - stamp) / 1e9, stamp)
    if change != "unbracketed":
        write(1.1, frame="new" if change == "reset" else "old")
    seat = {"along_m": 0, "lateral_m": 0, "heading_deg": 0, "inliers": 0.9, "margin": 0.6}
    anchor = keeper.record("C1", "docked", seat, observation)
    assert (anchor is not None) == (change == "stationary")


def test_a_new_epoch_rearms_startup_after_an_anchor_and_a_gap_invalidates_an_open_probe():
    events, odom = [], {"pose": _pose(epoch=7)}
    keeper, t, docks = _keeper(events, odom)
    ask = lambda lag: keeper.probe_request(True, docks, lag)
    first, _ = _still_frames(ask, t)
    assert keeper.note_probe_match({"bay1": _seat()}, first).odom_pose.epoch == 7
    t["now"] += 130
    odom["pose"] = _pose(epoch=8)
    assert keeper.current() is None
    delayed, _ = _still_frames(ask, t)
    t["now"] += 2
    assert ask(0.0) is None
    assert keeper.note_probe_match({"bay1": _seat()}, delayed) is None
    newest, _ = _still_frames(ask, t)
    assert keeper.note_probe_match({"bay1": _seat()}, newest).odom_pose.epoch == 8
    assert len(events) == 2


@pytest.mark.parametrize("change", ["add", "edit_in_place", "remove"])
def test_reference_changes_during_a_startup_fit_require_a_new_frame(change):
    from types import SimpleNamespace
    events = []
    initial = ("C1", "C2") if change == "remove" else ("C1",)
    keeper, t, docks = _keeper(events, {"pose": _pose()}, initial)
    ask = lambda lag: keeper.probe_request(True, docks, lag)
    old_id, old_refs = _still_frames(ask, t)
    if change == "add":
        docks.append(SimpleNamespace(id="C2", metadata={"reference_scan": {"ranges": [2.0]}}))
    elif change == "edit_in_place":
        docks[0].metadata["reference_scan"]["ranges"][0] = 3.0
        assert old_refs["C1"]["ranges"] == [1.0]
    else:
        docks.pop()
    old_matches = {name: _seat() if name == "C1" else _seat(x=0.12) for name in old_refs}
    assert keeper.note_probe_match(old_matches, old_id) is None and not events
    t["now"] += 0.25
    new_id, new_refs = ask(0.0)
    assert new_id != old_id and new_refs == {d.id: d.metadata["reference_scan"] for d in docks}
    matches = {name: _seat() if name == "C1" else _seat(x=0.12) for name in new_refs}
    assert keeper.note_probe_match(matches, new_id).dock_id == "C1" and len(events) == 1


def test_a_later_unique_identity_completes_only_its_own_already_docked_seat_once():
    from dataclasses import replace
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    _fixed_odom(p.manager)
    p.battery.percent = 100.0
    p.manager.dock()
    deliver = p.manager.note_bay_seat_matches
    held = []
    p.manager.note_bay_seat_matches = lambda matches, rid: held.append((matches, rid))
    accept = p.manager.note_bay_scan_match
    def first_replay_a_previous_run(match, *, request_id):
        if p.manager._bay_phases._req_kind == "seat":
            frame = p.manager._pending_seat_anchor.frame
            old = replace(frame, run_id="previous", observation=replace(frame.observation, seen_at=frame.observation.seen_at - 1))
            accept(None, request_id=request_id, seat_frame=old)
            assert p.manager._bay_phases._req_open == request_id
            return accept(match, request_id=request_id, seat_frame=frame)
        return accept(match, request_id=request_id)
    p.manager.note_bay_scan_match = first_replay_a_previous_run
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01)))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None
    matches, frame = held[-1]
    # A different run with the same dock and request number cannot satisfy this capture.
    deliver(matches, replace(frame, run_id="older-run"))
    deliver(matches, replace(frame))
    assert p.manager.status().anchor is None
    deliver(matches, frame)
    deliver(matches, frame)
    assert p.manager.status().anchor.dock_id == "bay1"
    assert sum(kind == "docking.anchor" for kind, data in p.events) == 1


def test_a_replaced_reference_after_identification_but_before_docked_withholds_the_anchor():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=(), charges=False)
    with_reference(p)
    _fixed_odom(p.manager)
    p.battery.percent = 100.0
    p.manager.dock()
    deliver = p.manager.note_bay_seat_matches
    def reteach_before_docked(matches, frame):
        deliver(matches, frame)
        assert p.manager.state is DockState.DOCKING
        dock = p.manager._db.get("bay1")
        scan = dock.metadata["reference_scan"]
        dock.metadata["reference_scan"] = {**scan, "range_max": scan["range_max"] + 0.1}
    p.manager.note_bay_seat_matches = reteach_before_docked
    run_row(p, row, until=answer_kinds(zone=good(x=0.15), entry=good(x=0.15), seat=good(x=0.01)))
    assert p.manager.state is DockState.DOCKED and p.manager.status().anchor is None
    assert not any(kind == "docking.anchor" for kind, data in p.events)
