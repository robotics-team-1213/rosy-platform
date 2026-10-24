import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest

from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_information import LocalControlInformation
from fleet.server.task_store import FleetTaskStore


def producer(raw=None, *, tasks=None, active=None, sampled_at=998.0):
    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [
        {"id": "R"},
        {"id": "A", "parent": "R", "resources": ["robot:a", "robot:missing", "signal:s"]},
        {"id": "A1", "parent": "A", "resources": ["robot:child"]},
    ]})
    calls = []

    async def gather():
        calls.append(True)
        return raw if raw is not None else {"robots": []}

    local = LocalControlInformation(
        SimpleNamespace(unit_id="A", topology=topology), gather=gather, tasks=tasks,
        map_snapshot=lambda: active, clock=lambda: 50.0,
        sampled_at=lambda: sampled_at, wall_clock=lambda: 1000.0)
    return local, calls


def robot():
    return {"robot_id": "a", "online": True, "_state_mono": 43.0,
            "gather_source": "hub", "endpoint": "private", "map_pose": {"x": 999.0},
            "state": {"mode": "IDLE", "map_id": "_site", "pose": {"x": 1.0, "y": 2.0, "yaw": 0.3},
                      "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                      "battery": {"percent": 72.0}, "safety": {"estop": False},
                      "evidence": {"pose": {"evidence": "fresh"},
                                   "battery": {"evidence": "delayed"},
                                   "safety": {"evidence": "fresh"}},
                      "operator": "private", "token": "private"}}


def test_owned_projection_preserves_channels_and_shared_cache_without_mutation():
    raw = {"robots": [robot(), dict(robot(), robot_id="child"), dict(robot(), robot_id="foreign")]}
    before = deepcopy(raw)
    local, calls = producer(raw)
    summary, detail = asyncio.run(local.read())
    assert len(calls) == 1 and raw == before
    assert summary.unit_id == "A" and summary.parent == "R"
    assert summary.robots_total == 2 and summary.robots_online == 1
    assert summary.age_s == detail.age_s == 2.0
    assert summary.sampled_at == datetime.fromtimestamp(998.0, timezone.utc)
    assert summary.availability == detail.availability == "AVAILABLE"
    shown, missing = detail.robots
    assert shown.robot_id == "a" and shown.state_age_s == 7.0
    assert shown.battery_percent == 72.0 and shown.estop is False
    assert shown.evidence == {"pose": "fresh", "battery": "delayed", "safety": "fresh"}
    assert shown.pose.model_dump() == {"x": 1.0, "y": 2.0, "yaw": 0.3,
                                      "map_id": "_site", "source": "core", "frame": "map"}
    assert missing.robot_id == "missing" and missing.online is False
    assert missing.pose is missing.battery_percent is missing.estop is None
    assert missing.evidence == dict.fromkeys(("pose", "battery", "safety"), "unknown")
    payload = detail.model_dump_json()
    assert "private" not in payload and "foreign" not in payload and "child" not in payload
    assert "_state_mono" not in payload and "map_pose" not in payload


@pytest.mark.parametrize("evidence", ["disconnected", "unavailable", "unknown", None, "invented"])
def test_channel_evidence_does_not_turn_default_sensor_values_into_observations(evidence):
    row = robot()
    row["state"]["evidence"] = {channel: {"evidence": evidence} for channel in ("pose", "battery", "safety")}
    local, _ = producer({"robots": [row]})
    _, detail = asyncio.run(local.read())
    shown = detail.robots[0]
    assert shown.pose is shown.battery_percent is shown.estop is None
    expected = evidence if evidence in {"disconnected", "unavailable", "unknown"} else "unknown"
    assert set(shown.evidence.values()) == {expected}


@pytest.mark.parametrize("change", [
    {"localization": None}, {"localization": {"state": "UNKNOWN", "pose_frame": "map"}},
    {"localization": {"state": "LOCALIZED", "pose_frame": "odom"}},
    {"map_id": None}, {"map_id": "bad/map"}, {"pose": {"x": 1.0, "y": 2.0}},
    {"pose": {"x": float("nan"), "y": 2.0, "yaw": 0.0}},
    {"pose": {"x": "1.0", "y": 2.0, "yaw": 0.0}},
    {"pose": {"x": True, "y": 2.0, "yaw": 0.0}},
])
def test_pose_requires_core_localized_map_coordinates_and_identity(change):
    row = robot()
    row["state"].update(change)
    local, _ = producer({"robots": [row]})
    assert asyncio.run(local.read())[1].robots[0].pose is None


@pytest.mark.parametrize("battery,estop", [(None, None), (101.0, "false"), (float("inf"), 0), (True, 1)])
def test_malformed_values_are_null_even_when_channel_is_fresh(battery, estop):
    row = robot()
    row["state"]["battery"]["percent"] = battery
    row["state"]["safety"]["estop"] = estop
    local, _ = producer({"robots": [row]})
    shown = asyncio.run(local.read())[1].robots[0]
    assert shown.battery_percent is None and shown.estop is None


def test_offline_cached_body_does_not_publish_sensor_values():
    row = dict(robot(), online=False)
    local, _ = producer({"robots": [row]})
    shown = asyncio.run(local.read())[1].robots[0]
    assert shown.pose is shown.battery_percent is shown.estop is shown.mode is None
    assert shown.evidence["pose"] == "fresh"


def test_cached_source_time_is_not_replaced_by_projection_time():
    local, _ = producer(sampled_at=990.0)
    summary, detail = asyncio.run(local.read())
    assert summary.availability == detail.availability == "STALE"
    assert summary.age_s == detail.age_s == 10.0
    assert summary.sampled_at == datetime.fromtimestamp(990.0, timezone.utc)
    assert summary.dispatch is detail.dispatch is None


def test_projection_work_does_not_hide_source_age(monkeypatch):
    from fleet.server import control_unit_information as module
    from core_common.protocol.integrated_control import ControlDispatchFence
    wall = [1000.0]
    local, _ = producer()
    local.wall_clock = lambda: wall[0]

    def delayed_read(*args):
        wall[0] = 1010.0
        return [], False, 0, ControlDispatchFence(authority_epoch=1, generation=2)

    monkeypatch.setattr(module, "_task_projection", delayed_read)
    summary, detail = asyncio.run(local.read())
    assert summary.age_s == detail.age_s == 12.0
    assert summary.availability == detail.availability == "STALE"
    assert summary.dispatch is detail.dispatch is None


def test_duplicate_owned_rows_fail_without_choosing_a_state():
    local, _ = producer({"robots": [robot(), robot()]})
    with pytest.raises(ValueError, match="DUPLICATE_ROBOT"):
        asyncio.run(local.read())


def test_stop_pending_comes_from_journal_and_failure_cannot_report_zero():
    local, _ = producer()
    local.pending_stops = lambda: 2
    assert asyncio.run(local.read())[0].stop_pending == 2

    def unavailable():
        raise sqlite3.OperationalError("private journal unavailable")

    local.pending_stops = unavailable
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(local.read())


def test_gather_failure_propagates_for_collector_stale_handling():
    local, _ = producer()

    async def unavailable():
        raise ConnectionError("gather unavailable")

    local.gather = unavailable
    with pytest.raises(ConnectionError, match="gather unavailable"):
        asyncio.run(local.read())


@pytest.mark.parametrize("stamp", [None, 0.0, 1001.0, float("nan"), True])
def test_missing_or_invalid_gather_time_cannot_look_fresh(stamp):
    local, _ = producer(sampled_at=stamp)
    with pytest.raises(ValueError, match="SAMPLE"):
        asyncio.run(local.read())


def test_tasks_filter_ownership_in_sql_before_latest_page_and_count(tmp_path):
    store = FleetTaskStore(tmp_path / "tasks.sqlite3")
    with sqlite3.connect(store.path) as connection:
        rows = []
        for index in range(305):
            owned = index < 105
            status = "HOLD" if index == 99 else "RUNNING" if index < 100 else "COMPLETED"
            rows.append((f"task-{index:03}", "a" if owned else "child", "navigate", "operator",
                         "private-actor", str(index), status,
                         "private-reason", '{"private":"request"}', '{"private":"evidence"}',
                         "2026-10-24T00:00:00+00:00", f"2026-10-24T00:{index // 60:02}:{index % 60:02}+00:00"))
        connection.executemany(
            "INSERT INTO fleet_tasks (task_id,robot_id,task_type,source,actor_id,request_key,status,"
            "reason,request_json,evidence_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.execute("UPDATE fleet_dispatch_control SET authority_epoch=3,generation=7 WHERE control_id=1")
    local, _ = producer(tasks=store)
    summary, detail = asyncio.run(local.read())
    assert summary.tasks_active == 100
    assert summary.dispatch.authority_epoch == 3 and detail.dispatch.generation == 7
    assert len(detail.tasks) == 100 and detail.tasks_truncated is True
    assert detail.tasks[0].task_id == "task-104" and detail.tasks[-1].task_id == "task-005"
    assert {task.robot_id for task in detail.tasks} == {"a"}
    assert all(task.updated_at.utcoffset().total_seconds() == 0 for task in detail.tasks)
    assert "private" not in detail.model_dump_json()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_tasks").fetchone()[0] == 305
        assert connection.execute("SELECT generation FROM fleet_dispatch_control").fetchone()[0] == 7


def test_task_timestamp_without_timezone_is_rejected(tmp_path):
    store = FleetTaskStore(tmp_path / "tasks.sqlite3")
    store.create_task(task_id="bad-time", robot_id="a", task_type="navigate", source="operator",
                      actor_id="private", request_key="key", request={}, evidence=None)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE fleet_tasks SET updated_at='2026-10-24T00:00:00'")
    local, _ = producer(tasks=store)
    with pytest.raises(ValueError):
        asyncio.run(local.read())


def active_map(*, points=None):
    model = SimpleNamespace(map_id="_site", survey={"actor": "private"},
                            places=[SimpleNamespace(id="_park", name="Park", x=1.0, y=2.0,
                                                    operator="private")],
                            edges=[SimpleNamespace(id="_lane", polyline=points or [(0.0, 0.0), (1.0, 2.0)],
                                                   evidence={"secret": "private"})])
    return (4, model, object(), object())


def test_active_map_projection_has_unit_local_identity_and_no_evidence_metadata():
    local, _ = producer(active=active_map())
    projection = local.map()
    summary, detail = asyncio.run(local.read())
    assert summary.map == detail.map == projection.map
    assert projection.unit_id == "A" and projection.config_revision == "v1"
    assert projection.map.model_dump() == {"map_id": "_site", "version": 4, "frame": "unit_local"}
    assert projection.places[0].model_dump() == {"id": "_park", "label": "Park", "x": 1.0, "y": 2.0}
    assert projection.lanes[0].points[1].model_dump() == {"x": 1.0, "y": 2.0}
    payload = json.loads(projection.model_dump_json())
    assert set(payload) == {"unit_id", "config_revision", "map", "places", "lanes"}
    assert "private" not in str(payload)
    assert producer()[0].map() is None


def test_map_geometry_budget_is_enforced_before_large_projection():
    local, _ = producer(active=active_map(points=[(0.0, 0.0)] * 20_001))
    with pytest.raises(ValueError, match="MAP"):
        local.map()
