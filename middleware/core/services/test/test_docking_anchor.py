"""The seat anchor: "seated in bay X now" as an odom-bound pair for Fleet (dock_anchor.py)."""

from __future__ import annotations

import math

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
    keeper = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: events.append((ty, data)), wall=lambda: WALL, mono=lambda: t["now"])
    return keeper, t, [type("D", (), {"id": d, "metadata": {"reference_scan": {"ranges": [1.0]}}})() for d in docks]


def _pose(x=1.0, epoch=2):
    return OdomPose(x=x, y=0.0, yaw=0.0, stamp=WALL - 0.1, epoch=epoch, mono_s=1.0)


def _seat(**over):
    args = dict(x=0.004, y=0.002, heading=math.radians(1.0), inliers=0.95, margin=0.6, median_m=0.002)
    args.update(over)
    return BayScanPose(**args)


def test_the_startup_probe_asks_only_after_the_robot_stood_still_and_accepts_a_seat_fit():
    events, odom = [], {"pose": _pose()}
    keeper, t, docks = _keeper(events, odom)
    assert keeper.probe_request(True, docks) is None                     # first look: the robot has not been still long enough
    t["now"] = 1.0
    assert keeper.probe_request(True, docks) is None
    t["now"] = 2.5
    request = keeper.probe_request(True, docks)
    assert request is not None and request[1] == "bay1"
    anchor = keeper.note_probe_match(_seat(), request[0])
    assert anchor is not None and anchor.source == "startup_probe" and anchor.confirmation == "lidar_reference" and anchor.odom_pose.epoch == 2
    assert [e for e in events if e[0] == "docking.anchor"][0][1]["source"] == "startup_probe"
    t["now"] = 30.0
    assert keeper.probe_request(True, docks) is None                     # done: one anchor per run until the next record


def test_the_probe_refuses_a_weak_or_off_seat_fit_or_a_robot_that_moved_and_is_bounded_per_bay():
    for bad in (_seat(inliers=0.65), _seat(margin=0.2), _seat(x=0.05), _seat(y=0.04), _seat(heading=0.2), None):
        events, odom = [], {"pose": _pose()}
        keeper, t, docks = _keeper(events, odom)
        keeper.probe_request(True, docks)
        t["now"] = 3.0
        request = keeper.probe_request(True, docks)
        assert request is not None and keeper.note_probe_match(bad, request[0]) is None and not events
    events, odom = [], {"pose": _pose()}
    keeper, t, docks = _keeper(events, odom)
    keeper.probe_request(True, docks)
    t["now"] = 3.0
    request = keeper.probe_request(True, docks)
    odom["pose"] = _pose(x=1.02)                                          # it moved 2 cm while the scan was matched
    assert keeper.note_probe_match(_seat(), request[0]) is None
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
    p.manager._anchor._mono = lambda: t["now"]
    assert p.manager.anchor_probe_request() is None                       # first look arms the stillness timer
    t["now"] = 3.0
    request = p.manager.anchor_probe_request()
    assert request is not None and request[1] == "bay1"                   # idle, still, reference-scan bay: it asks
    t["now"] = 10.0
    p.safety.estop = True
    assert p.manager.anchor_probe_request() is None                       # an e-stopped robot is not probed
    p.safety.estop = False
    p.manager._state = DockState.DOCKING
    assert p.manager.anchor_probe_request() is None                       # nor while docking
    events, odom = [], {"pose": _pose()}
    keeper, t2, docks = _keeper(events, odom)
    assert keeper.note_probe_match(_seat(), 99) is None                   # no open request
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
    p.manager._anchor._odom = lambda: OdomPose(x=1.0, y=2.0, yaw=0.3, stamp=WALL - 0.1, epoch=3, mono_s=1.0)
    p.manager._anchor._wall = lambda: WALL
    p.manager._anchor._mono = lambda: t["now"]
    monkeypatch.setattr(bay_scan_pose, "locate", lambda ref, live: BayScanPose(x=0.004, y=0.002, heading=0.01, inliers=0.95, margin=0.6, median_m=0.002))
    services = _services(p.manager)
    assert p.manager.body_scan_rear_overhang() is None                    # no dock active: the old early return
    for now in (0.0, 1.0, 3.0, 3.5, 4.0):
        t["now"] = now
        bay_body_scan(services, _open_scan(), received_at=p.clock.now)
    for _ in range(100):
        if p.manager.status().anchor is not None:
            break
        time.sleep(0.02)
    anchor = p.manager.status().anchor
    assert anchor is not None and anchor.source == "startup_probe" and anchor.dock_id == "bay1"
    # the probe is wrapped: a raising manager method must not break the front-clearance path
    q = a_bay()
    q.manager.dock()
    q.manager.anchor_probe_request = lambda: (_ for _ in ()).throw(RuntimeError("probe broke"))
    bay_body_scan(_services(q.manager), _open_scan(), received_at=q.clock.now)
    assert q.manager._bay_phases._body is not None

def test_the_anchor_is_stamped_with_the_map_generation_when_the_core_has_one():
    events, odom = [], {"pose": _pose()}
    cfg = DockingConfig()
    keeper = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: events.append((ty, data)), wall=lambda: WALL,
                              map_generation_provider=lambda: 1234)
    seat = {"along_m": 0.001, "lateral_m": 0.0, "heading_deg": 0.5, "inliers": 0.95, "margin": 0.6}
    assert keeper.record("bay1", "docked", seat).map_generation == 1234
    plain = DockAnchorKeeper(cfg, lambda: odom["pose"], lambda: "map-1", lambda ty, sev, data: None, wall=lambda: WALL)
    assert plain.record("bay1", "docked", seat).map_generation is None
