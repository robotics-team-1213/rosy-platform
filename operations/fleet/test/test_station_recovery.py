"""D-721 Amendment (S1): the pure station recovery decision, and the routes that show and record it.

Nothing here may command a robot: the approval answers ``started: false`` and sends nothing.
"""
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from fleet.charge_bays import Bay, ChargeBays, RobotView
from fleet.server.auth.site_auth import build_role_guards
from fleet.server.station_recovery_routes import install_station_recovery_routes
from fleet.station_recovery import decide
from rosy_account.principal import SitePrincipal, legacy_grants

BAYS = [Bay("C1", -0.4, 0.5), Bay("C2", -0.2, 0.5)]
LOCALIZED = SimpleNamespace(state="LOCALIZED", x=1.0, y=2.0)


def plan_for(*views, bays=BAYS):
    plan = ChargeBays()
    plan.observe(0.0, list(views), bays)
    return plan.plan(list(views), bays)


def row(robot_id="r1", *, level="warning", percent=18.0, evidence="fresh", age=0.5, bound=5.0,
        online=True, estop=False, mode="IDLE", navigation="IDLE", docking="UNDOCKED", rule_m="idle", health=True):
    battery = {"evidence": evidence, "sample_age_s": age, "stale_after_s": bound, "level": level, "percent": percent}
    return {"robot_id": robot_id, "online": online,
            "state": {"mode": mode, "navigation": navigation, "safety": {"estop": estop},
                      "docking": {"state": docking}},
            "power_health": {"battery": battery} if health else None, "rule_m": {"state": rule_m}}


def free_plan():
    return plan_for(RobotView("r1", True, 18.0, None, (5.0, 5.0), False))


def test_a_low_battery_robot_that_can_be_served_gets_the_first_free_bay():
    answer = decide(row(), LOCALIZED, free_plan(), False)
    assert (answer["request"], answer["bay"], answer["reason"]) == (True, "C1", None)
    assert (answer["level"], answer["percent"]) == ("warning", 18.0)


@pytest.mark.parametrize("level", ["warning", "critical", "deep"])
def test_every_level_from_warning_down_asks(level):
    assert decide(row(level=level), LOCALIZED, free_plan(), False)["request"] is True


def test_a_healthy_battery_or_an_offline_robot_is_not_asked():
    assert decide(row(level="ok", percent=80.0), LOCALIZED, free_plan(), False) is None
    assert decide(row(online=False), LOCALIZED, free_plan(), False) is None


@pytest.mark.parametrize("make", [
    lambda: row(evidence="stale"),
    lambda: row(evidence="missing", age=None, percent=None),
    lambda: row(health=False),
    lambda: row(age=9.0),                      # labelled fresh, older than its own bound
    lambda: row(age=None),
    lambda: row(level="mystery"),
])
def test_unknown_battery_evidence_is_never_ok_and_never_a_low_battery_claim(make):
    answer = decide(make(), LOCALIZED, free_plan(), False)
    assert answer["request"] is False and answer["reason"] == "battery_evidence_missing"
    assert answer["bay"] is None and answer["level"] is None and answer["percent"] is None


def test_stale_evidence_with_a_healthy_looking_level_is_still_unknown():
    answer = decide(row(level="ok", percent=90.0, evidence="stale"), LOCALIZED, free_plan(), False)
    assert answer["reason"] == "battery_evidence_missing"


@pytest.mark.parametrize("kwargs, expected", [
    ({"estop": True}, "already_stopped"),
    ({"mode": "EMERGENCY"}, "already_stopped"),
    ({"rule_m": "bounded"}, "busy"),
    ({"mode": "NAVIGATION"}, "busy"),
    ({"mode": "MANUAL"}, "busy"),
    ({"mode": "DOCKING"}, "busy"),
    ({"navigation": "NAVIGATING"}, "busy"),
    ({"docking": "UNDOCKING"}, "busy"),
])
def test_a_stopped_or_busy_robot_is_refused_with_its_reason(kwargs, expected):
    answer = decide(row(**kwargs), LOCALIZED, free_plan(), False)
    assert (answer["request"], answer["bay"], answer["reason"]) == (True, None, expected)


def test_an_emergency_stop_beats_busy():
    assert decide(row(estop=True, mode="NAVIGATION"), LOCALIZED, free_plan(), False)["reason"] == "already_stopped"


def test_no_bays_on_the_map_or_no_map_is_no_station():
    assert decide(row(), LOCALIZED, None, False)["reason"] == "no_station"
    assert decide(row(), LOCALIZED, {"bays": []}, False)["reason"] == "no_station"


@pytest.mark.parametrize("pose", [None, SimpleNamespace(state="UNKNOWN"), SimpleNamespace(state="DEGRADED"),
                                  SimpleNamespace(state="BRIDGED")])
def test_a_pose_that_is_not_localized_is_position_unknown(pose):
    assert decide(row(), pose, free_plan(), False)["reason"] == "position_unknown"


def test_another_robot_on_its_way_holds_this_one():
    answer = decide(row(), LOCALIZED, free_plan(), True)
    assert (answer["request"], answer["bay"], answer["reason"]) == (True, None, "another_returning")


def test_full_bays_are_no_free_bay_and_an_unknown_bay_is_not_called_free():
    parked = [RobotView(f"p{i}", True, 60.0, None, (b.x, b.y), False) for i, b in enumerate(BAYS)]
    assert decide(row(), LOCALIZED, plan_for(*parked), False)["reason"] == "no_free_bay"
    unknown = {"bays": [{"bay": "C1", "state": "unknown", "robot_id": None},
                        {"bay": "C2", "state": "unknown", "robot_id": None}]}   # fix/trip-battery-bay-occupancy
    answer = decide(row(), LOCALIZED, unknown, False)
    assert (answer["reason"], answer["bays_unknown"], answer["bay"]) == ("no_free_bay", 2, None)


def test_a_robot_keeps_the_bay_the_plan_already_reserved_for_it():
    plan = plan_for(RobotView("other", True, 40.0, None, None, False), RobotView("r1", True, 12.0, None, None, False))
    assert [(b["bay"], b["robot_id"]) for b in plan["bays"]] == [("C1", "r1"), ("C2", None)]
    assert decide(row(percent=12.0, level="warning"), LOCALIZED, plan, False)["bay"] == "C1"


def test_a_robot_already_in_a_bay_has_nothing_to_recover():
    in_bay = RobotView("r1", True, 18.0, None, (BAYS[0].x, BAYS[0].y), False)
    assert decide(row(), LOCALIZED, plan_for(in_bay), False) is None


def test_reasons_follow_the_documented_precedence():
    both = decide(row(estop=True), None, None, True)
    assert both["reason"] == "already_stopped"
    assert decide(row(), None, None, True)["reason"] == "no_station"
    assert decide(row(), None, free_plan(), True)["reason"] == "position_unknown"


# ---- routes ---------------------------------------------------------------------------------

OPERATOR = SitePrincipal("alice", "operator", grants=legacy_grants({}))
VIEWER = SitePrincipal("vera", "viewer", grants=legacy_grants({}))


class Recorder:
    def __init__(self):
        self.events = []

    def record_event(self, action, principal_id, detail):
        self.events.append((action, principal_id, detail))


def make_client(rows, *, enabled=True, pose=LOCALIZED, bays=BAYS):
    app = FastAPI()
    recorder = app.state.site_maps = Recorder()
    views = [RobotView(r["robot_id"], r["online"], 18.0, None, None, False) for r in rows]
    app.state.charge_bays = ChargeBays()
    app.state.map_pose = SimpleNamespace(arbitrated_pose=lambda robot_id: pose)

    def authorize(request: Request):
        return {"operator": OPERATOR, "viewer": VIEWER}[request.headers.get("x-role", "operator")]

    require_viewer, _, require_named, require_proposer = build_role_guards(authorize, {"t": OPERATOR})

    async def gathered():
        return {"robots": rows}

    async def bay_inputs():
        return (7, {}), views, bays

    install_station_recovery_routes(app, enabled, ([Depends(require_viewer)], require_named, require_proposer),
                                    gathered, bay_inputs)
    return TestClient(app), recorder


def test_disabled_by_default_lists_nothing_and_refuses_approval():
    client, recorder = make_client([row()], enabled=False)
    body = client.get("/api/fleet/station-recovery").json()
    assert body == {"enabled": False, "reason": "disabled", "map_version": None, "requests": [], "dispatch": False}
    refused = client.post("/api/fleet/station-recovery/r1/approve")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "STATION_RECOVERY_DISABLED"
    assert recorder.events == []


def test_enabled_list_shows_requests_with_reasons_and_sends_nothing():
    rows = [row("r1", percent=12.0), row("r2", percent=18.0, estop=True), row("r3", level="ok", percent=90.0),
            row("r4", evidence="stale")]
    client, _ = make_client(rows)
    body = client.get("/api/fleet/station-recovery").json()
    got = {a["robot_id"]: (a["request"], a["bay"], a["reason"]) for a in body["requests"]}
    assert body["enabled"] is True and body["map_version"] == 7 and body["dispatch"] is False
    assert got == {"r1": (True, "C1", None), "r2": (True, None, "already_stopped"),
                   "r4": (False, None, "battery_evidence_missing")}


def test_two_askers_are_never_offered_the_same_bay():
    client, _ = make_client([row("r1", percent=19.0), row("r2", percent=17.0)])
    bays = {a["robot_id"]: a["bay"] for a in client.get("/api/fleet/station-recovery").json()["requests"]}
    assert bays == {"r2": "C1", "r1": "C2"}


def test_a_viewer_may_read_but_not_approve():
    client, recorder = make_client([row()])
    assert client.get("/api/fleet/station-recovery", headers={"x-role": "viewer"}).status_code == 200
    assert client.post("/api/fleet/station-recovery/r1/approve", headers={"x-role": "viewer"}).status_code == 403
    assert recorder.events == []


@pytest.mark.parametrize("make, reason", [
    (lambda: row(estop=True), "already_stopped"),
    (lambda: row(rule_m="bounded"), "busy"),
    (lambda: row(evidence="stale"), "battery_evidence_missing"),
    (lambda: row(level="ok", percent=90.0), "no_request"),
])
def test_approving_a_request_that_is_not_actionable_is_409_with_the_reason_and_records_nothing(make, reason):
    client, recorder = make_client([make()])
    refused = client.post("/api/fleet/station-recovery/r1/approve")
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "STATION_RECOVERY_NOT_ACTIONABLE", "reason": reason}
    assert recorder.events == []


def test_approving_without_a_trusted_pose_or_for_an_unknown_robot_is_refused():
    client, recorder = make_client([row()], pose=SimpleNamespace(state="UNKNOWN"))
    assert client.post("/api/fleet/station-recovery/r1/approve").json()["detail"]["reason"] == "position_unknown"
    assert client.post("/api/fleet/station-recovery/ghost/approve").json()["detail"]["reason"] == "no_request"
    assert recorder.events == []


def test_an_approved_request_is_recorded_for_the_named_operator_and_starts_nothing():
    client, recorder = make_client([row()])
    response = client.post("/api/fleet/station-recovery/r1/approve")
    assert response.status_code == 200
    body = response.json()
    assert (body["approved"], body["started"], body["reason"], body["bay"]) == (True, False, "not_implemented", "C1")
    assert recorder.events == [("station_recovery_approved", "alice",
                                {"robot_id": "r1", "bay": "C1", "level": "warning", "percent": 18.0,
                                 "map_version": 7, "started": False})]

# ---- a state with missing facts is unknown, never "idle and clear" ----------------------------------

def _drop(path):
    def mutate(r):
        target = r
        for key in path[:-1]:
            target = target[key]
        target.pop(path[-1])
    return mutate


@pytest.mark.parametrize("mutate", [
    lambda r: r["state"].clear(),
    _drop(("state", "safety")), _drop(("state", "safety", "estop")), _drop(("state", "mode")), _drop(("rule_m",)),
    lambda r: r["state"].update(mode="WEIRD"),
    lambda r: r["state"].update(mode=None),
    lambda r: r["state"]["safety"].update(estop=None),
    lambda r: r["state"]["safety"].update(estop="false"),
    lambda r: r.update(rule_m=None),
])
def test_missing_state_facts_answer_state_unknown_and_never_a_bay(mutate):
    candidate = row()
    mutate(candidate)
    answer = decide(candidate, LOCALIZED, free_plan(), False)
    assert (answer["request"], answer["bay"], answer["reason"]) == (True, None, "state_unknown")


def test_a_known_stop_still_wins_over_unknown_facts():
    candidate = row(estop=True)
    candidate["state"].pop("mode")
    assert decide(candidate, LOCALIZED, free_plan(), False)["reason"] == "already_stopped"


def test_approving_with_an_empty_state_is_refused_with_the_unknown_reason():
    candidate = row()
    candidate["state"] = {}
    client, recorder = make_client([candidate])
    refused = client.post("/api/fleet/station-recovery/r1/approve")
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "state_unknown"
    assert recorder.events == []
