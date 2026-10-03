from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


rclpy = pytest.importorskip("rclpy")


def test_node_uses_assembled_core_services_for_startup_and_shutdown(
        monkeypatch, tmp_path):
    from core import node as node_module

    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("model: pinky_pro\n", encoding="utf-8")
    capability_path = tmp_path / "capabilities.yaml"
    capability_path.write_text("{}\n", encoding="utf-8")

    events = SimpleNamespace(subscribe=Mock(), publish=Mock())
    state = SimpleNamespace(set_map_id=Mock(), set_safety_policy_provider=Mock())
    line_follow = SimpleNamespace(config=SimpleNamespace(lidar_forward_deg=180.0),
                                  use_lidar_forward=Mock())
    limits = SimpleNamespace(max_linear=0.3, max_angular=1.0, manual_linear=0.2,
                             manual_angular=0.8, fleet_linear=0.25, fleet_angular=0.9)
    runtime_probe = SimpleNamespace(attach_ros_graph_provider=Mock())
    services = SimpleNamespace(
        identity=SimpleNamespace(robot_id="rosy_01"),
        events=events,
        state=state,
        safety=SimpleNamespace(limits=limits, policy_required=False, shadow=None,
                               shadow_record_errors=0),
        line_follow=line_follow,
        runtime_probe=runtime_probe,
        control_adapter=None,
    )
    monkeypatch.setattr(node_module.CoreServices, "build", Mock(return_value=services))

    profile = SimpleNamespace(model="pinky_pro")
    monkeypatch.setattr("core_common.profile.RobotProfile.load", Mock(return_value=profile))

    adapter = SimpleNamespace(
        config=SimpleNamespace(mode="off"),
        mode_error="",
        bind_safety=Mock(),
        close=Mock(),
    )
    monkeypatch.setattr(
        "core.bridge.control_sensor_adapter.build_control_adapter",
        Mock(return_value=(adapter, [])),
    )
    monkeypatch.setattr(
        "core.system.ros_graph.RosGraphMonitor",
        Mock(return_value=SimpleNamespace(snapshot=Mock())),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.bridge.ros_bridge",
        SimpleNamespace(RosBridge=Mock(return_value=object())),
    )
    start_api = Mock()
    monkeypatch.setattr(node_module.RosyCoreNode, "_start_api", start_api)

    config = {
        "robot": {
            "profile": str(profile_path),
            "capabilities": str(capability_path),
        },
        "navigation": {"map_id": "map-v2"},
    }

    rclpy.init()
    core_node = None
    try:
        core_node = node_module.RosyCoreNode(config)

        assert core_node.core is services
        state.set_map_id.assert_called_once_with("map-v2")
        adapter.bind_safety.assert_called_once_with(services.safety)
        line_follow.use_lidar_forward.assert_called_once()
        state.set_safety_policy_provider.assert_called_once()
        events.subscribe.assert_called_once()
        events.publish.assert_any_call(
            "system.boot",
            source="core",
            data={"version": node_module.SOFTWARE_VERSION},
        )
        start_api.assert_called_once_with()

        core_node.shutdown()
        events.publish.assert_any_call(
            "system.shutdown", severity="warning", source="core")
        adapter.close.assert_called_once_with()
    finally:
        if core_node is not None:
            core_node.destroy_node()
        rclpy.shutdown()
