"""D-1005: speed limits are the operator's to set under the signed ceiling, and a sealed measured speed binds all driving."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from core_features.command import approval_trials as trials_module
from core_features.safety.limits import SpeedLimits
from core_features.safety.limits import BatteryPolicy
from core_features.safety.manager import SafetyManager
from core_api_web.api.v1 import speed_settings
from core_api_web.api.v1.speed_settings import SpeedSettingError, sealed_speeds, validate

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # alone-loadable: sibling fixtures without the dir conftest
from test_navigation_approval_api import OWNER, drive, robot, trials  # noqa: E402,F401  (fixtures)


ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


@pytest.fixture
def client(core_client):
    return core_client()


def _safety(**changes) -> SafetyManager:
    return SafetyManager(SpeedLimits(**changes), BatteryPolicy())


def _clip(safety, scope, linear=1.0, angular=1.0):
    return safety.clip(linear, angular, scope)


# -- the binding -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scope", ["manual", "nav", "fleet"])
def test_a_sealed_speed_bounds_every_scope(scope):
    safety = _safety(approved_linear=0.02, approved_angular=0.07)
    assert _clip(safety, scope) == (pytest.approx(0.02), pytest.approx(0.07))


@pytest.mark.parametrize("scope,expected", [("manual", (0.15, 0.60)), ("nav", (0.20, 0.80)), ("fleet", (0.20, 0.80))])
def test_without_a_sealed_speed_the_old_limits_stand(scope, expected):
    assert _clip(_safety(), scope) == pytest.approx(expected)


def test_a_lower_user_setting_still_wins_over_a_higher_sealed_speed():
    safety = _safety(approved_linear=0.10, approved_angular=0.40, manual_linear=0.05, manual_angular=0.2)
    assert _clip(safety, "manual") == (pytest.approx(0.05), pytest.approx(0.2))


def test_the_running_trial_may_use_its_own_speed_and_the_binding_returns_after():
    limits = SpeedLimits(approved_linear=0.02, approved_angular=0.07)
    safety = SafetyManager(limits, BatteryPolicy())
    limits.trial_cap = (0.10, 0.40)
    assert _clip(safety, "manual", 0.10, 0.40) == (pytest.approx(0.10), pytest.approx(0.40))
    limits.trial_cap = None
    assert _clip(safety, "manual", 0.10, 0.40) == (pytest.approx(0.02), pytest.approx(0.07))


def test_the_signed_ceiling_still_caps_a_trial_speed():
    limits = SpeedLimits(approved_linear=0.02, approved_angular=0.07)
    limits.trial_cap = (5.0, 5.0)
    assert SafetyManager(limits, BatteryPolicy()).clip(5.0, 5.0, "manual") == (pytest.approx(0.15), pytest.approx(0.60))


def test_settings_load_from_config_and_default_to_the_old_values():
    plain = SpeedLimits.from_config(profile=SimpleNamespace(max_linear_velocity=0.2, max_angular_velocity=0.8),
                                    nav_cfg={}, safety_cfg={})
    assert (plain.approved_linear, plain.approved_angular) == (None, None)
    assert (plain.approval_linear, plain.approval_angular, plain.approval_travel_m) == (0.02, 0.07, 0.06)
    set_ = SpeedLimits.from_config(profile=SimpleNamespace(max_linear_velocity=0.2, max_angular_velocity=0.8), nav_cfg={},
                                   safety_cfg={"approved_linear": 0.1, "approved_angular": 0.4, "approval_linear": 0.08})
    assert (set_.approved_linear, set_.approved_angular, set_.approval_linear) == (0.1, 0.4, 0.08)


# -- the ceiling ---------------------------------------------------------------------------------------------

def test_values_inside_the_ceiling_pass_and_map_to_limit_fields():
    values = validate({"manual_linear": 0.2, "trial_angular": 0.8, "trial_travel_m": 0.25}, SpeedLimits())
    assert values == {"manual_linear": 0.2, "approval_angular": 0.8, "approval_travel_m": 0.25}


@pytest.mark.parametrize("name,value", [("manual_linear", 0.2001), ("manual_angular", 0.81), ("trial_linear", 0.21),
                                        ("trial_angular", 0.9), ("trial_travel_m", 0.26)])
def test_a_value_above_the_ceiling_is_refused_not_clipped(name, value):
    with pytest.raises(SpeedSettingError, match="signed ceiling"):
        validate({name: value}, SpeedLimits())


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.01, True, "0.1"])
def test_bad_numbers_are_refused(value):
    with pytest.raises(SpeedSettingError):
        validate({"manual_linear": value}, SpeedLimits())


def test_a_trial_cannot_be_set_to_zero_but_a_manual_stop_can():
    assert validate({"manual_linear": 0}, SpeedLimits()) == {"manual_linear": 0.0}
    with pytest.raises(SpeedSettingError):
        validate({"trial_linear": 0}, SpeedLimits())


def test_the_travel_ceiling_pair_and_the_stop_allowance_fit_the_native_ceiling():
    import mapping_approval
    assert speed_settings.TRAVEL_RUN_CEILING_M == trials_module.TRAVEL_RUN_CEILING_M
    worst = trials_module.TRAVEL_RUN_CEILING_M + mapping_approval.CEILING_LINEAR_MPS * trials_module.STOP_LATENCY_S
    assert worst <= mapping_approval.TRAVEL_CEILING_M


@pytest.mark.parametrize("approval,expected", [
    ({"valid": True, "measured_linear_mps": 0.1, "measured_angular_rps": 0.4}, (0.1, 0.4)),
    ({"valid": False, "measured_linear_mps": 0.1, "measured_angular_rps": 0.4}, None),
    ({"valid": True, "measured_linear_mps": None, "measured_angular_rps": None}, None),
    ({"valid": True, "measured_linear_mps": 0, "measured_angular_rps": 0.4}, None),
    ({"valid": True, "measured_linear_mps": "0.1", "measured_angular_rps": 0.4}, None),
    (None, None)])
def test_only_a_valid_approval_with_both_speeds_yields_a_sealed_speed(approval, expected):
    assert sealed_speeds(approval) == expected


# -- the API -------------------------------------------------------------------------------------------------

@pytest.fixture
def overlay(tmp_path, monkeypatch):
    path = tmp_path / "rosy.yaml"
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", path)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    return path


def test_an_operator_sets_speeds_and_the_change_is_recorded(client, overlay):
    tc, svc = client
    response = tc.put("/api/v1/safety/speed-limits", headers=OPERATOR,
                      json={"manual_linear": 0.10, "trial_linear": 0.05, "trial_travel_m": 0.1})
    assert response.status_code == 200, response.text
    limits = response.json()["limits"]
    assert (limits["manual_linear"], limits["trial_linear"], limits["trial_travel_m"]) == (0.10, 0.05, 0.1)
    assert (svc.safety.limits.manual_linear, svc.safety.limits.approval_linear) == (0.10, 0.05)
    assert "approval_linear: 0.05" in overlay.read_text(encoding="utf-8")
    event = [e for e in svc.events.history() if e.type == "config.changed"][-1]
    assert event.data["key"] == "safety.speed_limits" and event.data["by"]
    assert event.data["changes"]["manual_linear"] == [0.15, 0.10]


def test_a_viewer_cannot_set_speeds_and_nothing_changes(client, overlay):
    tc, svc = client
    assert tc.put("/api/v1/safety/speed-limits", headers=VIEWER, json={"manual_linear": 0.01}).status_code == 403
    assert svc.safety.limits.manual_linear == 0.15 and not overlay.exists()


@pytest.mark.parametrize("body", [{"manual_linear": 0.21}, {"trial_angular": 0.81}, {"trial_travel_m": 0.3},
                                  {"manual_angular": -1}, {"manual_linear": 0.1, "trial_linear": 9}])
def test_over_the_ceiling_is_a_400_and_none_of_the_request_applies(client, overlay, body):
    tc, svc = client
    response = tc.put("/api/v1/safety/speed-limits", headers=ADMIN, json=body)
    assert response.status_code == 400, response.text
    assert (svc.safety.limits.manual_linear, svc.safety.limits.approval_linear) == (0.15, 0.02)
    assert not overlay.exists()


def test_an_unknown_field_is_refused_and_an_empty_request_changes_nothing(client, overlay):
    tc, svc = client
    assert tc.put("/api/v1/safety/speed-limits", headers=ADMIN, json={"max_linear": 5}).status_code in (400, 422)
    assert tc.put("/api/v1/safety/speed-limits", headers=ADMIN, json={}).status_code == 200
    assert svc.safety.limits.max_linear == 0.20 and not overlay.exists()


def test_the_old_limits_route_refuses_instead_of_clipping(client, overlay):
    tc, svc = client
    assert tc.put("/api/v1/safety/limits", headers=ADMIN, json={"manual_angular": 0.9}).status_code == 400
    assert svc.safety.limits.manual_angular == 0.60


def test_the_state_shows_what_drives_now(client, overlay):
    tc, svc = client
    svc.safety.limits.approved_linear, svc.safety.limits.approved_angular = 0.02, 0.07
    limits = tc.get("/api/v1/safety/state", headers=VIEWER).json()["limits"]
    assert (limits["effective_manual_linear"], limits["effective_manual_angular"]) == (0.02, 0.07)
    assert limits["manual_linear"] == 0.15 and limits["approved_linear"] == 0.02


def test_a_manual_drive_command_is_held_to_the_sealed_speed(client, overlay):
    tc, svc = client
    svc.safety.limits.approved_linear, svc.safety.limits.approved_angular = 0.02, 0.07
    assert svc.safety.clip(0.15, 0.6, "manual") == (pytest.approx(0.02), pytest.approx(0.07))


# -- the sealed speed reaching CORE ---------------------------------------------------------------------------

def _svc():
    events = []
    return SimpleNamespace(config={}, safety=SimpleNamespace(limits=SpeedLimits()),
                           events=SimpleNamespace(publish=lambda *a, **k: events.append((a, k)))), events


def test_a_valid_reply_binds_saves_and_is_recorded_once(monkeypatch):
    from core_api_web.api.v1 import navigation_approval as route
    saved = []
    monkeypatch.setattr(route, "patch_local_config", saved.append)
    svc, events = _svc()
    data = {"approval": {"valid": True, "measured_linear_mps": 0.1, "measured_angular_rps": 0.4}}
    route._bind_sealed_speed(svc, data)
    route._bind_sealed_speed(svc, data)
    assert (svc.safety.limits.approved_linear, svc.safety.limits.approved_angular) == (0.1, 0.4)
    assert saved == [{"safety": {"approved_linear": 0.1, "approved_angular": 0.4}}] and len(events) == 1


def test_an_invalid_or_speedless_reply_never_loosens_a_bound_limit(monkeypatch):
    from core_api_web.api.v1 import navigation_approval as route
    monkeypatch.setattr(route, "patch_local_config", lambda patch: None)
    svc, _ = _svc()
    svc.safety.limits.approved_linear, svc.safety.limits.approved_angular = 0.1, 0.4
    route._bind_sealed_speed(svc, {"approval": {"valid": False, "measured_linear_mps": None, "measured_angular_rps": None}})
    route._bind_sealed_speed(svc, {"approval": {"valid": True, "measured_linear_mps": None, "measured_angular_rps": None}})
    assert (svc.safety.limits.approved_linear, svc.safety.limits.approved_angular) == (0.1, 0.4)


def test_a_failed_save_still_binds_in_memory(monkeypatch):
    from core_api_web.api.v1 import navigation_approval as route

    def fail(_patch):
        raise OSError("read-only")
    monkeypatch.setattr(route, "patch_local_config", fail)
    svc, _ = _svc()
    route._bind_sealed_speed(svc, {"approval": {"valid": True, "measured_linear_mps": 0.1, "measured_angular_rps": 0.4}})
    assert svc.safety.limits.approved_linear == 0.1


# -- the re-approval trial ---------------------------------------------------------------------------------------

def test_by_default_the_trial_and_its_evidence_are_what_they_were(robot, trials, tmp_path):
    drive(robot, trials, "forward", "button_release")
    raw = json.loads((tmp_path / "trials/forward-button_release.json").read_text(encoding="ascii"))
    assert raw["requested_linear_mps"] == 0.02
    assert raw["travel_cap_m"] == pytest.approx(0.10)  # 0.06 run + 0.04 stop, the old 10 cm


def test_a_faster_trial_uses_the_operator_speed_and_records_a_wider_travel_cap(robot, trials, tmp_path):
    robot.limits.manual_linear, robot.limits.approval_linear, robot.limits.approval_travel_m = 0.15, 0.10, 0.12
    drive(robot, trials, "forward", "button_release", hold_s=1.0)
    raw = json.loads((tmp_path / "trials/forward-button_release.json").read_text(encoding="ascii"))
    assert raw["requested_linear_mps"] == 0.10
    assert raw["travel_cap_m"] == pytest.approx(0.12 + 0.10 * 0.65)


def test_the_trial_speed_never_exceeds_the_signed_ceiling_or_the_user_manual_setting(robot, trials):
    robot.limits.approval_linear, robot.limits.manual_linear, robot.limits.max_linear = 0.5, 0.15, 0.2
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    assert robot.commanded[0] == 0.15


def test_the_trial_binding_opens_for_the_trial_only(robot, trials):
    robot.limits.approval_linear = 0.08
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert robot.limits.trial_cap == (0.08, 0.07)
    trials.abort("end")
    assert robot.limits.trial_cap is None


def test_a_wider_run_distance_asks_for_more_room(robot, trials):
    robot.limits.approval_travel_m = 0.25
    robot.scan = {**robot.scan, "ranges": [0.30] * 360}
    with pytest.raises(trials_module.TrialRefused) as refused:
        trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_a_fast_trial_needs_room_for_its_stop_not_only_its_run(robot, trials):
    robot.limits.manual_linear, robot.limits.approval_linear, robot.limits.approval_travel_m = 0.2, 0.2, 0.25
    robot.scan = {**robot.scan, "ranges": [0.45] * 360}  # 0.38 m free ahead: the 0.30 m run + margin fits, run + stop does not
    with pytest.raises(trials_module.TrialRefused) as refused:
        trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_a_trial_thread_that_crashes_closes_the_trial_speed(robot, trials):
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert robot.limits.trial_cap is not None
    trials.tick = lambda: 1 / 0
    with pytest.raises(ZeroDivisionError):
        trials._run()
    assert robot.limits.trial_cap is None and not trials.active


@pytest.mark.parametrize("bad", [math.nan, 0, -0.02, math.inf])
def test_a_sealed_speed_that_cannot_bind_is_refused_at_load(bad):
    with pytest.raises(ValueError, match="approved_linear"):
        SpeedLimits.from_config(profile=SimpleNamespace(max_linear_velocity=0.2, max_angular_velocity=0.8),
                                nav_cfg={}, safety_cfg={"approved_linear": bad})


def test_the_robot_state_tells_a_console_what_a_manual_drive_may_use(client, overlay):
    tc, svc = client
    svc.safety.limits.manual_linear, svc.safety.limits.manual_angular = 0.12, 0.5
    shown = tc.get("/api/v1/robot/state", headers=VIEWER).json()["speed_limits"]
    assert (shown["manual_linear"], shown["manual_angular"], shown["approved_linear"]) == (0.12, 0.5, None)
    svc.safety.limits.approved_linear, svc.safety.limits.approved_angular = 0.02, 0.07
    shown = tc.get("/api/v1/robot/state", headers=VIEWER).json()["speed_limits"]
    assert (shown["manual_linear"], shown["manual_angular"], shown["set_linear"]) == (0.02, 0.07, 0.12)
    assert (shown["max_linear"], shown["max_angular"]) == (0.2, 0.8)


def test_an_operator_names_who_asked_and_the_record_keeps_it(client, overlay):
    tc, svc = client
    body = {"manual_linear": 0.1, "operator_name": "person-a"}
    assert tc.put("/api/v1/safety/speed-limits", headers=OPERATOR, json=body).status_code == 200
    event = [e for e in svc.events.history() if e.type == "config.changed"][-1]
    assert event.data["by"] == "person-a" and event.data["changes"]["manual_linear"] == [0.15, 0.1]


def test_the_limits_route_lets_an_operator_set_only_the_manual_speeds(client, overlay):
    tc, svc = client
    assert tc.put("/api/v1/safety/limits", headers=OPERATOR, json={"manual_linear": 0.1}).status_code == 200
    assert tc.put("/api/v1/safety/limits", headers=OPERATOR, json={"fleet_loss_policy": "HOLD"}).status_code == 403
    event = [e for e in svc.events.history() if e.type == "config.changed"][-1]
    assert event.data["changes"] == {"manual_linear": 0.1} and event.data["by"]
