"""The shared manual sentence reaches the existing authenticated CORE mode owner."""
import pytest

from core_common.intent import IntentError, interpret

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


@pytest.mark.parametrize("robot", [None, "pinky"])
def test_manual_is_a_bodyless_current_or_named_robot_intent(robot):
    document = {"do": "manual", **({"robot": robot} if robot else {})}
    call, = interpret(document)
    assert call.scope == "robot" and call.robot == robot
    assert call.path == "/api/v1/mode" and call.body == {}


@pytest.mark.parametrize("extra", [{"mode": "IDLE"}, {"linear": 0.1}, {"x": 1}])
def test_manual_rejects_caller_controlled_mode_or_motion(extra):
    with pytest.raises(IntentError) as rejected:
        interpret({"do": "manual", **extra})
    assert rejected.value.code == "UNKNOWN_FIELD"


def test_manual_intent_changes_mode_through_the_existing_owner(core_client):
    client, services = core_client()
    response = client.post("/api/v1/do", headers=OPERATOR, json={"do": "manual"})
    assert response.status_code == 200, response.text
    assert services.modes.mode.value == "MANUAL"
    assert response.json()["steps"][0]["result"] == {"mode": "MANUAL"}


def test_manual_intent_does_not_release_emergency_stop(core_client):
    client, services = core_client()
    stopped = client.post("/api/v1/safety/stop", headers=OPERATOR)
    assert stopped.status_code == 200, stopped.text
    before = services.modes.mode
    response = client.post("/api/v1/do", headers=OPERATOR, json={"do": "manual"})
    assert response.status_code == 409, response.text
    assert services.modes.mode is before


def test_manual_intent_keeps_operator_authorization(core_client):
    client, services = core_client()
    before = services.modes.mode
    response = client.post("/api/v1/do", headers={"Authorization": "Bearer rosy-dev-viewer"},
                           json={"do": "manual"})
    assert response.status_code == 403, response.text
    assert services.modes.mode is before
