"""D-400: the state block node.py publishes, built without ROS."""

from types import SimpleNamespace

from core.safety_params import SafetyParams
from core.safety_policy_status import safety_policy_block


def test_block_reports_configured_and_effective_mode():
    adapter = SimpleNamespace(config=SimpleNamespace(mode="off"), mode_error="ValueError: no IR stream")
    params = SafetyParams({"lidar_yaw_offset": 3.17}, {"lidar_yaw_offset": "line_follow: hand value"}, "r" * 16)

    block = safety_policy_block("shadow", adapter, params, shadow=None)

    assert block == {"mode": "shadow", "mode_effective": "off", "mode_error": "ValueError: no IR stream",
                     "revision": "r" * 16, "sources": {"lidar_yaw_offset": "line_follow: hand value"},
                     "shadow": None}


def test_block_carries_the_shadow_snapshot():
    adapter = SimpleNamespace(config=SimpleNamespace(mode="shadow"), mode_error="")
    shadow = SimpleNamespace(snapshot=lambda: {"counts": {"allow": 1}})

    block = safety_policy_block("shadow", adapter, None, shadow=shadow, record_errors=2)

    assert block["shadow"] == {"counts": {"allow": 1}, "record_errors": 2}
    assert block["revision"] == "" and block["sources"] == {}


def test_block_from_a_real_shadow_log_validates_as_the_published_status():
    from core_common.protocol.schemas import SafetyPolicyStatus
    from core_features.safety.shadow import ShadowLog

    adapter = SimpleNamespace(config=SimpleNamespace(mode="shadow"), mode_error="")
    block = safety_policy_block("shadow", adapter, None, shadow=ShadowLog(), record_errors=0)

    status = SafetyPolicyStatus.model_validate(block)

    assert status.mode == "shadow" and status.shadow is not None
