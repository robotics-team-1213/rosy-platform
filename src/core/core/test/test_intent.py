"""통역기: JSON/YAML '이렇게 해' → 기존 API 주소. ROS 이름은 거절한다."""

import pytest

from core_common.intent import IntentError, interpret, loads, verbs


def test_json_navigate_becomes_the_goal_call():
    calls = interpret({"do": "navigate", "x": 1.5, "y": -2, "yaw": 0.3, "robot": "rosy_01"})
    assert len(calls) == 1
    call = calls[0]
    assert call.path == "/api/v1/navigation/goal"
    assert call.kind == "NAVIGATE"
    assert call.scope == "robot"
    assert call.robot == "rosy_01"
    assert call.body == {"x": 1.5, "y": -2, "yaw": 0.3}


def test_yaml_reads_the_same_sentence():
    calls = interpret(loads("do: stop\n"))
    assert calls[0].path == "/api/v1/safety/stop"
    assert calls[0].body == {}


def test_steps_stay_in_order_and_site_sentences_stay_site():
    calls = interpret({"steps": [
        {"do": "formation_start", "leader": "rosy_01", "formation": "COLUMN"},
        {"do": "estop"},
    ]})
    assert [call.verb for call in calls] == ["formation_start", "estop"]
    assert {call.scope for call in calls} == {"site"}
    assert calls[0].body["leader"] == "rosy_01"


def test_ros_payloads_are_not_a_sentence():
    with pytest.raises(IntentError) as caught:
        interpret({"do": "navigate", "x": 0, "y": 0, "cmd_vel": {}})
    assert caught.value.code == "FORBIDDEN"


def test_unknown_verb_and_missing_fields_fail():
    with pytest.raises(IntentError) as unknown:
        interpret({"do": "fly"})
    assert unknown.value.code == "UNKNOWN_VERB"
    with pytest.raises(IntentError) as missing:
        interpret({"do": "follow"})
    assert missing.value.code == "MISSING"


def test_peer_follow_is_not_scatterable():
    with pytest.raises(IntentError) as caught:
        interpret({"do": "follow", "target_robot_id": "rosy_02", "source": "peer"})
    assert caught.value.code == "FORBIDDEN"


def test_every_public_verb_has_a_path():
    extras = {
        "navigate": {"x": 0, "y": 0},
        "follow": {"target_robot_id": "rosy_02"},
        "formation_start": {"leader": "rosy_01"},
    }
    for name in verbs():
        call = interpret({"do": name, **extras.get(name, {})})[0]
        assert call.path.startswith("/api/")
