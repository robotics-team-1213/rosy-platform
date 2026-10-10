"""D-603: `POST/GET/DELETE /api/v1/motion/rotate_to` — who may turn the robot, the 409/403 refusals and
that the turn reaches the wheels only through the CommandManager arbiter (`select_output`)."""

from __future__ import annotations

from test_localization_mission import ADMIN, OPERATOR, VIEWER, _scan, _state, core  # noqa: F401

PATH = "/api/v1/motion/rotate_to"
NAMED = {"delta_deg": 45.0, "operator_name": "kim"}


def _code(response) -> str:
    return response.json()["error"]["code"]


def test_a_named_operator_turns_and_the_turn_goes_through_the_arbiter(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))  # a LOCALIZED robot may turn (D-603)
    started = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert started.status_code == 202, started.text
    assert started.json()["kind"] == "rotate_to" and started.json()["state"] == "running"
    services.loc_mission.tick()
    out = services.command.select_output()
    assert out.linear == 0.0 and 0.0 < out.angular <= 20.0 * 3.1416 / 180 + 1e-6
    assert client.get(PATH, headers=VIEWER).json()["state"] == "running"
    stopped = client.delete(PATH, headers=OPERATOR).json()
    assert stopped["state"] == "aborted" and stopped["reason"] == "cancelled" and "final_err_deg" in stopped
    assert services.modes.mode.value == "IDLE" and services.command.select_output().angular == 0.0
    events = [e.data for e in services.events.history() if e.type == "motion.rotate_to"]
    assert events[-1]["operator_name"] == "kim" and events[-1]["lease_owner"] is False


def test_who_may_ask(core):
    client, services = core
    anonymous = client.post(PATH, json={"delta_deg": 45.0}, headers=OPERATOR)
    assert anonymous.status_code == 403 and _code(anonymous) == "OPERATOR_NAME_REQUIRED"
    assert client.post(PATH, json=NAMED, headers=VIEWER).status_code == 403
    lease = {"lease_id": "l1", "trip_id": "t1", "holder": "site", "operator_name": "kim", "ttl_s": 5}
    assert client.put("/api/v1/trip-lease", json=lease, headers=OPERATOR).status_code == 200
    other = client.post(PATH, json=NAMED, headers=ADMIN)
    assert other.status_code == 409 and _code(other) == "TRIP_LEASED"
    owner = client.post(PATH, json={"delta_deg": 45.0}, headers=OPERATOR)  # the lease owner needs no name
    assert owner.status_code == 202, owner.text
    assert [e.data["lease_owner"] for e in services.events.history() if e.type == "motion.rotate_to"] == [True]


def test_refusals(core):
    client, services = core
    bad = client.post(PATH, json={"delta_deg": 200.0, "operator_name": "kim"}, headers=OPERATOR)
    assert bad.status_code == 400 and _code(bad) == "VALIDATION_ERROR"
    services.loc_mission.observe_scan(_scan(services, front_m=0.06, rest_m=0.06))
    near = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert near.status_code == 409 and _code(near) == "ROTATE_CLEARANCE"
    assert set(near.json()["error"]["detail"]) == {"nearest_m", "need_m"}
    services.loc_mission.observe_scan(_scan(services))
    services.safety.trigger_estop("test")
    estop = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert estop.status_code == 409 and _code(estop) == "EMERGENCY_ACTIVE"
    assert services.modes.mode.value == "EMERGENCY" and services.command.select_output().angular == 0.0


def test_manual_or_another_mission_is_busy(core):
    client, services = core
    assert client.post("/api/v1/localization/mission", headers=OPERATOR, json={
        "kind": "rotate_in_place", "max_distance_m": 0.0, "max_time_s": 30.0}).status_code == 202
    busy = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert busy.status_code == 409 and _code(busy) == "MOTION_BUSY"
    assert client.get(PATH, headers=VIEWER).json()["state"] == "idle"  # that mission is not a turn
    client.delete(PATH, headers=OPERATOR)
    assert services.loc_mission.status()["state"] == "running"  # DELETE stops only a turn
    services.loc_mission.end("cancelled")
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    manual = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert manual.status_code == 409 and _code(manual) == "MOTION_BUSY"


def test_capability_flag(core):
    client, _services = core
    assert client.get("/api/v1/system/capabilities", headers=VIEWER).json()["motion"] == {"rotate_to": True}
