"""D-59: 로봇 런타임은 사이트 버스가 아니다. 브로커·인지 cmd_vel 금지."""

from robot_contracts import ROOT, compose

_BROKER_TOKENS = (
    "kafka", "nats", "mqtt", "rabbitmq", "redis", "pulsar", "redpanda", "zenoh-router",
)


def test_robot_compose_has_no_site_broker_service():
    services = compose()["services"]
    assert set(services) == {"rosy-core", "rosy-motor", "rosy-io"}
    blob = (ROOT / "deploy" / "robot" / "compose.yaml").read_text(encoding="utf-8").lower()
    for token in _BROKER_TOKENS:
        assert token not in blob, token


def test_perception_sources_do_not_publish_cmd_vel():
    roots = [
        ROOT / "src" / "core" / "control" / "control" / "sensing" / "perception" / "camera_worker.py",
        ROOT / "src" / "core" / "control" / "control" / "camera_detect_node.py",
    ]
    for path in roots:
        text = path.read_text(encoding="utf-8")
        assert "cmd_vel" not in text, path
        assert "create_publisher" not in text or "Twist" not in text
