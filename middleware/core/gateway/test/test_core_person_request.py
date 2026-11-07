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
