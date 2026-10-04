"""D-347: 플래그별 capability lifecycle — 단일 어휘가 선에 실리는지.

`lifecycle_from`은 이미 있는 두 값(CAP-001 프로파일 선언과 runtime_truth의
플래그별 사유, D-32)을 한 어휘로 합칠 뿐 새 판정을 만들지 않는다.
`activating`은 온디맨드 그래프 기동을 위해 예약되어 있고 아직 생산자가
없다 — 그 예약은 가정이 아니라 핀으로 지킨다.
"""

from __future__ import annotations

import yaml

from core.services import CoreServices
from core_common.domain.capabilities import (
    CapabilityLifecycle,
    lifecycle_from,
    runtime_truth,
    withhold_hardware_flags,
)
from core_common.profile import RobotProfile, robot_config_dir


def _services(tmp_path, *, mode: str, deployment: str = ""):
    robot_dir = robot_config_dir("pinky_pro")
    config = {
        "robot": {"id": "rosy_19", "model": "pinky_pro"},
        "runtime": {"mode": mode, "navigation_backend": "localization",
                    "deployment": deployment},
    }
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    declared = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    return CoreServices.build(config, profile, declared, tmp_path / "waypoints.json"), declared


# --- derivation (ROS-free, pure) --------------------------------------------


def test_a_reasoned_flag_is_unavailable_with_every_reason():
    out = lifecycle_from(
        {"teleop": True, "slam": True, "docking": {"supported": False}},
        {"teleop": "runtime_mode:core"},
    )
    assert out["teleop"] == {
        "state": "unavailable",
        "reason": "runtime_mode:core",
        "reasons": ("runtime_mode:core",),
    }
    assert out["slam"] == {"state": "ready"}


def test_a_flag_the_profile_does_not_declare_is_absent():
    """설계 §7 — false는 생략된다. lifecycle이 CAP-001이 말하지 않은 것을
    광고하는 일은 없어야 한다."""
    out = lifecycle_from(
        {"teleop": True, "docking": {"supported": False}}, {})
    assert "docking.supported" not in out
    assert set(out) == {"teleop"}


def test_activating_is_reserved_and_never_produced():
    out = lifecycle_from({"teleop": True}, {})
    assert CapabilityLifecycle.ACTIVATING.value == "activating"
    assert all(entry["state"] != "activating" for entry in out.values()), (
        "on-demand graph start has no producer yet (D-347); a value in "
        "`activating` means someone started lane B without this contract"
    )


# --- consistency with the withheld block (one truth, two shapes) ------------


def test_withheld_and_lifecycle_agree_on_core_only_device(tmp_path):
    services, _ = _services(tmp_path, mode="core", deployment="device")
    truth = runtime_truth(services.config, services.state, services.readiness)
    data = withhold_hardware_flags(services.capability.to_dict(), truth.reasons)
    life = lifecycle_from(services.capability.to_dict(), truth.reasons)

    withheld = data.get("withheld") or {"flags": [], "reasons": {}}
    unavailable = {f for f, e in life.items() if e["state"] == "unavailable"}
    assert set(withheld["flags"]) == unavailable
    for flag in withheld["flags"]:
        assert life[flag]["reason"] == withheld["reasons"][flag]
    # core-only device: 선언된 하드웨어 플래그는 전부 보류 — 하나도 ready가 아니다.
    assert unavailable >= {
        "teleop", "navigation.goal_navigation", "slam", "swarm.follow"}
    assert not [f for f, e in life.items() if e["state"] == "ready"]


def test_lifecycle_never_exceeds_what_the_runtime_advertises(tmp_path):
    services, declared = _services(tmp_path, mode="motor")
    truth = runtime_truth(services.config, services.state, services.readiness)
    life = lifecycle_from(services.capability.to_dict(), truth.reasons)
    advertised = services.capability.to_dict()
    # motor 모드가 내린 플래그(slam=false)는 lifecycle에 없어야 한다.
    assert "slam" not in life
    assert declared["slam"] is True  # 프로파일 원본은 그대로 (D-295 masking 규칙)
    del advertised


# --- the wire surface (additive) --------------------------------------------


def test_capabilities_endpoint_carries_the_lifecycle_block(core_client):
    client, _ = core_client()
    viewer = {"Authorization": "Bearer rosy-dev-viewer"}
    response = client.get("/api/v1/system/capabilities", headers=viewer)
    assert response.status_code == 200
    body = response.json()

    life = body["lifecycle"]
    assert life, "the block must list every advertised flag"
    withheld = body.get("withheld") or {"flags": [], "reasons": {}}
    for flag in withheld["flags"]:
        assert life[flag]["state"] == "unavailable"
        assert life[flag]["reason"] == withheld["reasons"][flag]
    for flag, entry in life.items():
        assert entry["state"] in ("ready", "unavailable")
