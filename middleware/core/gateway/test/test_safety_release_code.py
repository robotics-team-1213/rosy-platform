"""v1.337: the e-stop release code root shows on the stopped screen; CORE takes it only to release."""

from __future__ import annotations

from test_auth_pairing import (  # noqa: F401  (robot is a fixture)
    CODE, CODE_ID, DEV_OPERATOR, DEV_VIEWER, OTHER_CODE, _pair, _state_file, robot, write_code,
)

RELEASE = "/api/v1/safety/release-code"


def _latched(robot, role="estop_release"):
    tc, svc, state, events = robot()
    write_code(robot.boot, role=role)
    assert tc.post("/api/v1/safety/stop", headers=DEV_VIEWER).status_code == 200
    return tc, svc, state


def test_the_screen_code_releases_once_and_tells_root(robot):
    tc, svc, state = _latched(robot)

    answer = tc.post(RELEASE, json={"code": CODE[:4] + "-" + CODE[4:]}, headers=DEV_OPERATOR)

    assert answer.status_code == 200 and answer.json() == {"estop": False}
    assert svc.safety.estop is False
    assert _state_file(state) == {"code_id": CODE_ID, "state": "used"}
    tc.post("/api/v1/safety/stop", headers=DEV_VIEWER)
    assert tc.post(RELEASE, json={"code": CODE}, headers=DEV_OPERATOR).status_code == 403


def test_a_release_code_never_logs_in_and_a_login_code_never_releases(robot):
    tc, svc, _ = _latched(robot)
    assert _pair(tc).status_code == 401

    tc, svc, state = _latched(robot, role="operator")
    refused = tc.post(RELEASE, json={"code": CODE}, headers=DEV_OPERATOR)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "CODE_REJECTED"
    assert svc.safety.estop is True and state.failures == {} and state.spent == set()


def test_a_robot_that_is_not_latched_keeps_its_code(robot):
    tc, _svc, state = robot()[:3]
    write_code(robot.boot, role="estop_release")

    refused = tc.post(RELEASE, json={"code": CODE}, headers=DEV_OPERATOR)

    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NOT_LATCHED"
    assert state.failures == {} and state.spent == set()


def test_a_viewer_cannot_release_with_a_code(robot):
    tc, svc, _ = _latched(robot)
    assert tc.post(RELEASE, json={"code": CODE}, headers=DEV_VIEWER).status_code == 403
    assert svc.safety.estop is True


def test_five_wrong_codes_burn_the_release_code(robot):
    tc, svc, state = _latched(robot)

    answers = [tc.post(RELEASE, json={"code": OTHER_CODE}, headers=DEV_OPERATOR) for _ in range(5)]

    assert [a.status_code for a in answers] == [403] * 5
    assert answers[-1].json()["error"]["detail"] == {"burned": True}
    assert _state_file(state) == {"code_id": CODE_ID, "state": "burned"}
    other = type(tc)(tc.app, client=("192.168.1.21", 50000))
    assert other.post(RELEASE, json={"code": CODE}, headers=DEV_OPERATOR).status_code == 403


def test_release_codes_are_refused_outside_the_robot_lan(robot):
    tc, svc, _ = robot(client=("8.8.8.8", 50000))
    write_code(robot.boot, role="estop_release")
    tc.post("/api/v1/safety/stop", headers=DEV_VIEWER)
    assert tc.post(RELEASE, json={"code": CODE}, headers=DEV_OPERATOR).status_code == 403
    assert svc.safety.estop is True
    assert svc.safety.estop is True
