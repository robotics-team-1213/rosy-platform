"""`payload-boot-smoke.yml` 계약 (D-444 P1.2).

같은 arm64 러너에서 payload artifact를 부팅해 세 웹 표면의 200+CSP를 관측한다.
수동 실행만, 비밀 없음(GITHUB_TOKEN 한정), 실패 시 로그 업로드 — D-437 워크플로
규율과 같은 문화다. 로컬 에뮬레이션 벤치는 binfmt 유실로 반복 불능이었음(2026-10-04,
3회) — 그래서 이 워크플로가 P1.2의 정본 자리다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/payload-boot-smoke.yml")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_manual_dispatch_only_no_schedule_or_push():
    flow = _workflow()
    assert set(flow.get("on", {}).keys()) == {"workflow_dispatch"}, \
        "수동 실행만 허용한다 — push마다 돌면 payload 빌드 비용이 배가된다"


def test_runs_in_the_ros_container_on_the_arm_runner():
    job = _workflow()["jobs"]["boot-smoke"]
    assert job["runs-on"] == "ubuntu-24.04-arm", "native arm64 — 에뮬레이션 금지(D-161 취지)"
    assert job["container"] == "ros:jazzy-ros-base", "ROS apt 소스는 컨테이너가 제공한다"
    assert 0 < int(job["timeout-minutes"]) <= 30


def test_no_secrets_beyond_the_job_token():
    flow = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert flow["permissions"] == {"contents": "read"}
    assert "secrets." not in text, "서명 키·비밀은 이 워크플로에 없다(D-437)"


def test_probes_all_three_web_surfaces_and_fails_on_missing_csp():
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in ("dashboard", "pilot", "console"):
        assert f'"/{path}"' in text or f"/{path}" in text, f"/{path} 프로브가 없다"
    assert "content-security-policy" in text, "CSP 헤더 확인이 없다(D-444 R1)"
    assert "exit 1" in text


def test_boots_from_the_payload_install_with_pinned_rmw_and_identity():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "release/install/setup.bash" in text
    assert "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in text, "CycloneDDS 핀(D-117)"
    assert "ROSY_ROBOT_NUMBER=1" in text, "신원 없으면 런타임이 멈춘다(D-33)"
    assert 'grep -q "core up"' in text


def test_uploads_the_boot_log_even_on_failure():
    job = _workflow()["jobs"]["boot-smoke"]
    steps = {s.get("name", ""): s for s in job["steps"]}
    upload = steps.get("Upload the boot log")
    assert upload and upload.get("if") == "always()", "실패 로그가 사라지면 관측이 불가하다"
