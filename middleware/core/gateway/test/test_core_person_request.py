"""D-721 Amendment (v1.372): the person request CORE holds. It shows; it never moves, releases or passes anything."""

import pytest

from core.bridge import display

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
FLEET = {"Authorization": "Bearer rosy-dev-operator"}
OTHER = {"Authorization": "Bearer rosy-dev-admin"}
URL = "/api/v1/person-request"
ID_A, ID_B = "a" * 32, "b" * 32


class _Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Executor:
    def __init__(self) -> None:
        self.goals, self.cancels = [], 0

    def send_goal(self, spec, *, correlation_id=None):
        self.goals.append(spec)

    def cancel_goal(self):
        self.cancels += 1

    def send_initial_pose(self, *a):
        return None


@pytest.fixture
def robot(core_client):
    client, services = core_client()
    clock = _Clock()
    services.person_request._now = clock
    services.nav.executor = _Executor()
    return client, services, clock


def _put(client, headers=FLEET, **over):
    body = {"request_id": ID_A, "kind": "unplug_charger", "text": "충전기를 뽑아 주세요", "why": "주행 시작", "ttl_s": 60, **over}
    return client.put(URL, json=body, headers=headers)


def test_put_get_delete(robot):
    client, _, _ = robot
    held = _put(client)
    assert held.status_code == 200 and held.json()["motion"] is False and held.json()["renewed"] is False
    shown = client.get(URL, headers=VIEWER).json()["person_request"]
    assert (shown["id"], shown["kind"], shown["face_text"], shown["remaining_s"]) == (ID_A, "unplug_charger",
                                                                                      "UNPLUG CHARGER", 60.0)
    assert _put(client).json()["renewed"] is True
    assert client.delete(f"{URL}/{ID_A}", headers=FLEET).json() == {"cleared": True, "motion": False}
    assert client.get(URL, headers=VIEWER).json()["person_request"] is None
    assert client.delete(f"{URL}/{ID_A}", headers=FLEET).json()["cleared"] is False


def test_only_an_operator_puts_and_a_bad_body_is_refused(robot):
    client, services, _ = robot
    assert _put(client, VIEWER).status_code == 403
    for over in ({"kind": "fly"}, {"ttl_s": 99999}, {"request_id": "short"}, {"text": ""}, {"extra": 1}):
        assert _put(client, **over).status_code in (400, 422)
    assert services.person_request.view() is None


def test_at_most_one_request_and_another_credential_cannot_take_it_over(robot):
    client, services, _ = robot
    _put(client)
    assert _put(client, request_id=ID_B, kind="move_robot").status_code == 200   # replaces: still one
    assert services.person_request.view()["id"] == ID_B
    assert _put(client, OTHER, request_id=ID_B).status_code == 403
    assert client.delete(f"{URL}/{ID_B}", headers=OTHER).status_code == 403
    assert services.person_request.view()["id"] == ID_B


def test_an_expired_request_is_gone_without_anyone_clearing_it(robot):
    client, services, clock = robot
    _put(client, ttl_s=30)
    clock.now += 29
    assert services.person_request.view()["remaining_s"] == 1.0
    clock.now += 2
    assert client.get(URL, headers=VIEWER).json()["person_request"] is None
    assert display.face_person_request(services.person_request.view()) == {"person_request": None}


def test_holding_or_ending_a_request_commands_nothing_and_does_not_release_a_stop(robot):
    client, services, _ = robot
    assert client.post("/api/v1/safety/stop", headers=VIEWER).status_code == 200
    before = (services.modes.mode, services.safety.estop, len(services.nav.executor.goals), services.nav.executor.cancels)
    assert before[1]   # the stop is latched
    _put(client)
    assert client.delete(f"{URL}/{ID_A}", headers=FLEET).status_code == 200
    _put(client, kind="plug_charger")
    after = (services.modes.mode, services.safety.estop, len(services.nav.executor.goals), services.nav.executor.cancels)
    assert after == before   # no goal, no cancel, no mode change, the stop still latched
    state = client.get("/api/v1/robot/state", headers=VIEWER).json()
    assert state["safety"]["estop"] is True


def test_the_face_hand_over_carries_the_ask_with_a_countdown_the_writer_does_not_rewrite_for(robot):
    _, services, clock = robot
    services.person_request.put(request_id=ID_A, kind="clear_area", text="x", why="", ttl_s=60, owner_id="o")
    first = display.face_person_request(services.person_request.view())
    assert first == {"person_request": {"id": ID_A, "kind": "clear_area", "remaining_s": 60.0}}
    clock.now += 5
    second = display.face_person_request(services.person_request.view())
    assert second["person_request"]["remaining_s"] == 55.0
    # a countdown tick alone is not a change worth an early write
    assert display._coarse({"battery_percent": 50, **first}) == display._coarse({"battery_percent": 50, **second})
    other = display.face_person_request({"id": ID_B, "kind": "clear_area", "remaining_s": 55.0})
    assert display._coarse({"battery_percent": 50, **first}) != display._coarse({"battery_percent": 50, **other})


def _as_account(client, sub="user-7"):
    """A person logged in with an account (D-757); the token path cannot make one."""
    from core_api_web.api.deps import AuthContext
    from core_api_web.api.v1.common import viewer
    client.app.dependency_overrides[viewer] = lambda: AuthContext("account:s1", "viewer", source="account",
                                                                  principal_ref=sub)


def test_only_a_person_logged_in_with_an_account_answers_at_the_robot_and_it_moves_nothing(robot):
    client, services, _ = robot
    _put(client)
    assert client.get(URL, headers=VIEWER).json()["can_answer"] is False
    refused = client.post(f"{URL}/{ID_A}/answer", json={"answer": "done"}, headers=FLEET)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "PERSON_LOGIN_REQUIRED"
    _as_account(client)
    try:
        assert client.get(URL).json()["can_answer"] is True
        assert client.post(f"{URL}/{ID_A}/answer", json={"answer": "start"}).status_code == 400   # CORE maps a bad body to 400
        assert client.post(f"{URL}/{ID_B}/answer", json={"answer": "done"}).status_code == 409
        said = client.post(f"{URL}/{ID_A}/answer", json={"answer": "cannot"}).json()
        client.post(f"{URL}/{ID_A}/answer", json={"answer": "done"})   # the first answer stands
    finally:
        client.app.dependency_overrides.clear()
    assert said["person_request"]["answer"] == {"answer": "cannot", "by": "user-7"}
    assert services.person_request.view()["answer"] == {"answer": "cannot", "by": "user-7"}
    assert services.nav.executor.goals == [] and services.nav.executor.cancels == 0
