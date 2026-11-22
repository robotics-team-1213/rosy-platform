"""A dock pose must not depend on a map that restarted (y8xs 2026-11-20: the SLAM map origin resets with the navigation stack) and a
Nav2 start refuses a map the LiDAR contradicts."""

from __future__ import annotations

import pytest

from core_features.docking.database import DockError
from core_features.docking.manager import DockState
from test_docking_bay import a_bay
from test_docking_bay_scan_pose import answer_kinds, good, stale_map, with_reference
from test_docking_bay_zone import a_row, run_row


def test_a_dock_taught_in_another_map_frame_is_refused_until_it_is_taught_again():
    p = a_bay()
    db = p.manager._db
    frame = {"id": "occupancy:aaa"}
    p.manager._map_id_provider = lambda: frame["id"]
    db.teach("bay1", 0.0, 0.0, 0.0, None)                # stamped with the frame it was taught in
    assert db.get("bay1").metadata["map_epoch"] == "occupancy:aaa"
    frame["id"] = "occupancy:bbb"                        # the SLAM map restarted
    with pytest.raises(DockError) as err:
        p.manager.dock()
    assert err.value.code == "MAP_FRAME_CHANGED" and "occupancy:aaa" in str(err.value)
    assert p.manager.state is not DockState.DOCKING
    db.teach("bay1", 0.0, 0.0, 0.0, None)
    p.manager.dock()
    assert p.manager.state is DockState.DOCKING


def test_the_same_frame_or_an_unknown_frame_or_a_plain_charger_dock_is_not_refused():
    p = a_bay()
    db = p.manager._db
    p.manager._map_id_provider = lambda: "occupancy:aaa"
    db.teach("bay1", 0.0, 0.0, 0.0, None)
    p.manager.dock()                                     # same frame
    assert p.manager.state is DockState.DOCKING
    q = a_bay()
    q.manager._db._docks["bay1"] = q.manager._db.get("bay1").model_copy(update={"metadata": {"map_epoch": "x"}})
    q.manager.dock()                                     # frame unknown now (no map id)
    assert q.manager.state is DockState.DOCKING
    r = a_bay()
    r.manager._map_id_provider = lambda: "occupancy:bbb"
    r.manager._db._docks["bay1"] = r.manager._db.get("bay1").model_copy(update={"metadata": {"map_epoch": "occupancy:aaa"}})
    r.manager._db._types["bay-line"] = r.manager._db._types["bay-line"].model_copy(update={"approach": "bearing", "staging_offset_m": 0.7})
    r.manager._dock_type = None
    r.manager.dock()                                     # not a bay-row (line) dock: no refusal
    assert r.manager.state is DockState.DOCKING


def test_a_dock_with_no_epoch_is_not_refused():
    p = a_bay()
    p.manager._db._docks["bay1"] = p.manager._db.get("bay1").model_copy(update={"metadata": {}})
    p.manager.dock()
    assert p.manager.state is DockState.DOCKING


def test_a_nav2_start_the_lidar_contradicts_is_refused_with_the_numbers():
    p, row = a_row(start=None, others=())
    with_reference(p, verified=True)             # even accepted site_pose_evidence does not override a LiDAR that contradicts the map pose
    stale_map(p, dx=-0.40, dyaw=0.0)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0)))
    assert p.manager.state is DockState.DOCK_FAILED and "map frame does not match the LiDAR" in p.manager._error, p.manager._error
    assert not p.world.goals


def test_a_nav2_start_the_lidar_agrees_with_goes_on():
    p, row = a_row(start=None, others=())
    with_reference(p)
    p.manager.dock()
    run_row(p, row, until=answer_kinds(zone=good(x=1.0)))
    assert p.world.goals and "map frame" not in (p.manager._error or "")
