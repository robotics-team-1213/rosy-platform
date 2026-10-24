"""Bounded observation and stop receipts carry scope without claiming physical safety."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError


STAMP = "2026-10-24T03:00:00Z"


@pytest.fixture
def wire():
    from core_common.protocol import integrated_control
    return integrated_control


def fence():
    return {"authority_epoch": 3, "generation": 7}


def map_ref():
    return {"map_id": "floor-1", "version": 2, "frame": "unit_local"}


def summary():
    return {"unit_id": "A", "parent": "R", "availability": "AVAILABLE",
            "sampled_at": STAMP, "age_s": 0.5, "robots_total": 2, "robots_online": 1,
            "tasks_active": 1, "map": map_ref(), "dispatch": fence(), "error": None}


def pose():
    return {"x": 1, "y": 2.5, "yaw": 0, "map_id": "floor-1", "source": "odometry", "frame": "odom"}


def robot():
    return {"robot_id": "robot-1", "online": True, "state_age_s": 0.5, "mode": "IDLE",
            "battery_percent": 75, "estop": False, "pose": pose()}


def task():
    return {"task_id": "task-1", "robot_id": "robot-1", "status": "RUNNING", "updated_at": STAMP}


def detail():
    return {"unit_id": "A", "config_revision": "lab-1", "availability": "AVAILABLE",
            "sampled_at": STAMP, "age_s": 0.5, "robots": [robot()], "tasks": [task()],
            "tasks_truncated": False, "map": map_ref(), "dispatch": fence()}


def geometry():
    return {"unit_id": "A", "config_revision": "lab-1", "map": map_ref(),
            "places": [{"id": "dock-1", "label": "Dock", "x": 1, "y": 2}],
            "lanes": [{"id": "lane-1", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 2}]}]}


def stop():
    return {"stop_id": "stop-1", "target_unit": "A", "config_revision": "lab-1",
            "expected_controls": {"A": fence()}}


def result():
    return {"unit_id": "A", "state": "ACKNOWLEDGED", "dispatch": fence(),
            "acknowledged_robots": 1, "unknown_robots": 1, "omx_state": "LOCAL_LATCHED",
            "physical_stop": "UNVERIFIED"}


def snapshot():
    return {"unit_id": "R", "origin_id": "R", "stop_id": "stop-1", "target_unit": "A",
            "config_revision": "lab-1", "results": [result()], "revision": 1}


def reconcile():
    return {"expected_generation": 7, "receiver_channels_terminated": True,
            "receivers_recommissioned": True, "evidence": "Operator verified receiver restart",
            "affected_units": ["A"]}


def stop_reference():
    return {"origin_id": "R", "stop_id": "stop-1", "target_unit": "A", "config_revision": "lab-1",
            "revision": 1, "incomplete": True, "local_reconciliation_required": True, "updated_at": STAMP}


@pytest.mark.parametrize("name,body", [
    ("ControlOverview", {"unit_id": "R", "config_revision": "lab-1", "units": [summary()]}),
    ("ControlUnitDetail", detail()), ("ControlMapSnapshot", geometry()),
    ("ControlStopRequest", stop()), ("ControlStopIngress", dict(stop(), origin_id="R")),
    ("ControlStopSnapshot", snapshot()), ("ControlStopReconcile", reconcile()),
])
def test_wire_roundtrip_preserves_owner_scope_and_stop_identity(wire, name, body):
    model = getattr(wire, name)
    value = model.model_validate(body)
    decoded = model.model_validate_json(value.model_dump_json())
    assert decoded == value
    for field in ("unit_id", "origin_id", "stop_id", "target_unit", "config_revision", "affected_units"):
        if field in body:
            assert decoded.model_dump(mode="json")[field] == body[field]
    field = next(iter(body))
    with pytest.raises(ValidationError):
        setattr(value, field, body[field])


@pytest.mark.parametrize("name,body,changes", [
    ("ControlDispatchFence", fence(), {"authority_epoch": True}),
    ("ControlDispatchFence", fence(), {"generation": "7"}),
    ("ControlDispatchFence", fence(), {"generation": -1}),
    ("ControlMapRef", map_ref(), {"version": True}),
    ("ControlMapRef", map_ref(), {"version": 0}),
    ("ControlMapRef", map_ref(), {"frame": "map"}),
    ("ControlUnitSummary", summary(), {"robots_online": 3}),
    ("ControlUnitSummary", summary(), {"robots_total": 257}),
    ("ControlUnitSummary", summary(), {"tasks_active": -1}),
    ("ControlUnitSummary", summary(), {"stop_pending": -1}),
    ("ControlUnitSummary", summary(), {"stop_pending": True}),
    ("ControlUnitSummary", summary(), {"age_s": True}),
    ("ControlUnitSummary", summary(), {"age_s": -0.1}),
    ("ControlUnitSummary", summary(), {"error": "timeout"}),
    ("ControlUnitSummary", summary(), {"error": "TIMEOUT\nSECRET"}),
    ("ControlUnitSummary", summary(), {"availability": "ONLINE"}),
    ("ControlUnitSummary", summary(), {"raw_state": {"token": "synthetic"}}),
    ("ControlRobotInfo", robot(), {"online": 1}),
    ("ControlRobotInfo", robot(), {"estop": "false"}),
    ("ControlRobotInfo", robot(), {"battery_percent": 100.1}),
    ("ControlRobotInfo", robot(), {"battery_percent": -1}),
    ("ControlRobotInfo", robot(), {"battery_percent": True}),
    ("ControlRobotInfo", robot(), {"mode": "x" * 33}),
    ("ControlRobotPose", pose(), {"x": True}),
    ("ControlRobotPose", pose(), {"frame": "unit_local"}),
    ("ControlRobotPose", pose(), {"source": "x" * 65}),
    ("ControlRobotPose", pose(), {"source": ""}),
    ("ControlTaskInfo", task(), {"status": "STOP_CONFIRMED"}),
    ("ControlTaskInfo", task(), {"status": "PENDING"}),
    ("ControlTaskInfo", task(), {"status": "APPROVING"}),
    ("ControlTaskInfo", task(), {"updated_at": "yesterday"}),
    ("ControlUnitDetail", detail(), {"tasks_truncated": 1}),
    ("ControlStopSnapshot", snapshot(), {"revision": 0}),
    ("ControlStopUnitResult", result(), {"acknowledged_robots": True}),
    ("ControlStopUnitResult", result(), {"unknown_robots": -1}),
    ("ControlStopUnitResult", result(), {"omx_state": "STOPPED"}),
    ("ControlStopUnitResult", result(), {"state": "STOPPED"}),
    ("ControlStopUnitResult", result(), {"error": "https://peer.invalid"}),
    ("ControlStopUnitResult", result(), {"error": "X" * 97}),
    ("ControlStopUnitResult", result(), {"error": True}),
    ("ControlMapPlace", geometry()["places"][0], {"label": "x" * 129}),
    ("ControlMapPoint", {"x": 0, "y": 0}, {"url": "https://peer.invalid"}),
])
def test_wire_rejects_coercion_and_out_of_contract_values(wire, name, body, changes):
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **changes))


@pytest.mark.parametrize("name,body,field", [
    ("ControlRobotPose", pose(), "yaw"), ("ControlMapPoint", {"x": 0, "y": 0}, "x"),
    ("ControlRobotInfo", robot(), "state_age_s"), ("ControlRobotInfo", robot(), "battery_percent"),
    ("ControlUnitSummary", summary(), "age_s"),
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_observation_values_are_rejected(wire, name, body, field, value):
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **{field: value}))


def test_unavailable_units_preserve_unknown_observations(wire):
    body = dict(summary(), availability="UNAVAILABLE", sampled_at=None, age_s=None,
                map=None, dispatch=None, error="PEER_TIMEOUT")
    value = wire.ControlUnitSummary.model_validate(body)
    assert value.dispatch is None and value.sampled_at is None
    assert value.error == "PEER_TIMEOUT"
    unknown = dict(robot(), state_age_s=None, mode=None, battery_percent=None, estop=None, pose=None)
    assert wire.ControlRobotInfo.model_validate(unknown).estop is None


@pytest.mark.parametrize("field,value", [
    ("actor_id", "operator-a"), ("origin_id", "spoofed"), ("token", "synthetic-token"),
    ("url", "https://peer.invalid"), ("target_unit", "https://peer.invalid"),
    ("config_revision", ""), ("stop_id", True),
    ("expected_controls", {}), ("expected_controls", {"https://peer.invalid": fence()}),
    ("expected_controls", {f"unit-{n}": fence() for n in range(65)}),
])
def test_stop_request_rejects_caller_authority_and_malformed_scope(wire, field, value):
    with pytest.raises(ValidationError):
        wire.ControlStopRequest.model_validate(dict(stop(), **{field: value}))


@pytest.mark.parametrize("field,value", [
    ("receiver_channels_terminated", False), ("receiver_channels_terminated", 1),
    ("receivers_recommissioned", False), ("receivers_recommissioned", "true"),
    ("expected_generation", True), ("expected_generation", -1),
    ("evidence", "too short"), ("evidence", "x" * 2049),
    ("affected_units", []), ("affected_units", ["A", "A"]),
    ("affected_units", [f"unit-{n}" for n in range(65)]), ("actor_id", "caller-claimed"),
])
def test_reconciliation_requires_explicit_bounded_operator_evidence(wire, field, value):
    with pytest.raises(ValidationError):
        wire.ControlStopReconcile.model_validate(dict(reconcile(), **{field: value}))


@pytest.mark.parametrize("state", [
    "PENDING", "SENDING", "ACKNOWLEDGED", "PARTIAL", "UNKNOWN", "STALE_FENCE", "NOT_REACHED",
    "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING",
])
def test_every_delivery_state_keeps_physical_stop_unverified(wire, state):
    value = wire.ControlStopUnitResult.model_validate(dict(result(), state=state))
    assert value.physical_stop == "UNVERIFIED"
    with pytest.raises(ValidationError):
        wire.ControlStopUnitResult.model_validate(dict(result(), state=state, physical_stop="CONFIRMED"))


@pytest.mark.parametrize("name,body,field,items", [
    ("ControlOverview", {"unit_id": "R", "config_revision": "lab-1"}, "units", [summary()] * 2),
    ("ControlUnitDetail", detail(), "robots", [robot()] * 2),
    ("ControlUnitDetail", detail(), "tasks", [task()] * 2),
    ("ControlStopSnapshot", snapshot(), "results", [result()] * 2),
    ("ControlMapSnapshot", geometry(), "places", geometry()["places"] * 2),
    ("ControlMapSnapshot", geometry(), "lanes", geometry()["lanes"] * 2),
])
def test_projection_lists_reject_duplicate_owner_resource_ids(wire, name, body, field, items):
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **{field: items}))


@pytest.mark.parametrize("name,body,field,item,id_field,count", [
    ("ControlOverview", {"unit_id": "R", "config_revision": "lab-1"}, "units", summary(), "unit_id", 65),
    ("ControlUnitDetail", detail(), "robots", robot(), "robot_id", 257),
    ("ControlUnitDetail", detail(), "tasks", task(), "task_id", 101),
    ("ControlStopSnapshot", snapshot(), "results", result(), "unit_id", 65),
    ("ControlMapSnapshot", geometry(), "places", geometry()["places"][0], "id", 501),
    ("ControlMapSnapshot", geometry(), "lanes", geometry()["lanes"][0], "id", 1001),
])
def test_projection_lists_have_hard_item_bounds(wire, name, body, field, item, id_field, count):
    items = [dict(item, **{id_field: f"item-{n}"}) for n in range(count)]
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **{field: items}))


def test_map_point_budget_applies_across_lanes(wire):
    points = [{"x": 1.25, "y": 2.5}] * 10_000
    body = dict(geometry(), lanes=[{"id": "one", "points": points}, {"id": "two", "points": points}])
    value = wire.ControlMapSnapshot.model_validate(body)
    assert sum(len(lane.points) for lane in value.lanes) == 20_000
    body["lanes"][1] = {"id": "two", "points": points + [{"x": 0, "y": 0}]}
    with pytest.raises(ValidationError):
        wire.ControlMapSnapshot.model_validate(body)
    with pytest.raises(ValidationError):
        wire.ControlMapLane(id="short", points=[{"x": 0, "y": 0}])


def test_summary_byte_budget_counts_utf8_within_resource_limits(wire):
    body = detail()
    body["robots"] = [dict(robot(), robot_id=f"robot-{n}", mode="\U0001f642" * 32,
                           pose=dict(pose(), source="\U0001f642" * 64)) for n in range(256)]
    assert len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > 128 * 1024
    with pytest.raises(ValidationError):
        wire.ControlUnitDetail.model_validate(body)


def test_robot_channel_evidence_preserves_partial_observation(wire):
    body = dict(robot(), evidence={"pose": "delayed", "battery": "unavailable", "safety": "unknown"},
                battery_percent=None, estop=None)
    value = wire.ControlRobotInfo.model_validate_json(json.dumps(body))
    assert value.model_dump(mode="json")["evidence"] == body["evidence"]
    assert value.battery_percent is None and value.estop is None
    assert wire.ControlRobotInfo.model_validate(robot()).evidence == {}
    assert wire.ControlUnitSummary.model_validate(summary()).stop_pending == 0
    assert wire.ControlUnitSummary.model_validate(dict(summary(), stop_pending=2)).stop_pending == 2
    assert wire.ControlStopUnitResult.model_validate(result()).error is None
    assert wire.ControlStopUnitResult.model_validate(dict(result(), error="PEER_TIMEOUT")).error == "PEER_TIMEOUT"


@pytest.mark.parametrize("evidence", [
    {"camera": "fresh"}, {"pose": "confirmed"}, {"pose": True},
    {"pose": "fresh", "battery": "fresh", "safety": "fresh", "raw": "fresh"},
])
def test_robot_channel_evidence_rejects_unknown_channels_and_claims(wire, evidence):
    with pytest.raises(ValidationError):
        wire.ControlRobotInfo.model_validate(dict(robot(), evidence=evidence))


@pytest.mark.parametrize("name,body,field", [
    ("ControlUnitSummary", summary(), "sampled_at"),
    ("ControlUnitDetail", detail(), "sampled_at"),
    ("ControlTaskInfo", task(), "updated_at"),
    ("ControlStopReference", stop_reference(), "updated_at"),
])
@pytest.mark.parametrize("value", ["2026-10-24T03:00:00", datetime(2026, 10, 24, 3)])
def test_wire_timestamps_require_timezone_evidence(wire, name, body, field, value):
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **{field: value}))


def test_map_ids_keep_existing_producer_leading_punctuation(wire):
    value = wire.ControlMapSnapshot.model_validate(dict(
        geometry(), map=dict(map_ref(), map_id="_site"),
        places=[dict(geometry()["places"][0], id="_dock")],
        lanes=[dict(geometry()["lanes"][0], id="-lane")]))
    assert value.map.map_id == "_site"
    assert value.places[0].id == "_dock" and value.lanes[0].id == "-lane"
    assert wire.ControlRobotPose.model_validate(dict(pose(), map_id=".site")).map_id == ".site"


@pytest.mark.parametrize("name,body,field,value", [
    ("ControlMapRef", map_ref(), "map_id", "floor/one"),
    ("ControlMapRef", map_ref(), "map_id", "x" * 65),
    ("ControlRobotPose", pose(), "map_id", "floor/one"),
    ("ControlMapPlace", geometry()["places"][0], "id", "dock/one"),
    ("ControlMapPlace", geometry()["places"][0], "id", "x" * 33),
    ("ControlMapLane", geometry()["lanes"][0], "id", "lane/one"),
    ("ControlMapLane", geometry()["lanes"][0], "id", "x" * 33),
])
def test_map_resource_ids_preserve_the_producer_bounds(wire, name, body, field, value):
    with pytest.raises(ValidationError):
        getattr(wire, name).model_validate(dict(body, **{field: value}))


def test_stop_history_roundtrips_identity_without_private_receipts(wire):
    reference = stop_reference()
    body = {"unit_id": "A", "config_revision": "lab-1", "stops": [reference]}
    history = wire.ControlStopHistory.model_validate(body)
    assert json.loads(history.model_dump_json())["stops"] == [reference]
    assert wire.ControlStopHistory.model_validate(dict(body, stops=[reference, dict(reference, origin_id="B")]))
    with pytest.raises(ValidationError):
        wire.ControlStopHistory.model_validate(dict(body, stops=[reference, reference]))
    for field in ("actor_id", "evidence", "raw_receipt"):
        with pytest.raises(ValidationError):
            wire.ControlStopHistory.model_validate(dict(body, stops=[dict(reference, **{field: "private"})]))


@pytest.mark.parametrize("changes", [
    {"revision": 0}, {"revision": True}, {"incomplete": 1}, {"local_reconciliation_required": "true"},
])
def test_stop_reference_is_strict_recovery_metadata(wire, changes):
    with pytest.raises(ValidationError):
        wire.ControlStopReference.model_validate(dict(stop_reference(), **changes))


def test_stop_history_has_a_bounded_number_of_unique_identities(wire):
    stops = [dict(stop_reference(), stop_id=f"stop-{n}") for n in range(101)]
    with pytest.raises(ValidationError):
        wire.ControlStopHistory(unit_id="A", config_revision="lab-1", stops=stops)


def test_integrated_models_keep_the_canonical_schema_exports(wire):
    from core_common.protocol import schemas

    models = {name: value for name, value in vars(wire).items() if name.startswith("Control")}
    assert models
    assert all(getattr(schemas, name) is value for name, value in models.items())
