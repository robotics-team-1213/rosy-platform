"""D-347 B레인 관문 측정 도구의 안전 핀 (기준선 문서 §5).

측정 스크립트는 단위를 멈추는 힘을 가진다 — 이 시험은 그 힘의 경계를 고정한다:
A/B 로 멈출 수 있는 단위는 카메라·navigation 뿐이고(core·io 금지), 멈춘 단위는
되살린다. 거부는 무권한으로도 판정 가능해야 한다(스크립트가 allowlist 를
root 검사보다 먼저 본다는 것도 이 시험의 일부다).
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "verify" / "measure-resident-cpu.sh"
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_the_script_parses():
    assert subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True).returncode == 0


@pytest.mark.skipif(BASH is None, reason="bash is required")
@pytest.mark.parametrize("forbidden", [
    "rosy-io.service",       # 안전·구동 기본층
    "rosy-core.service",     # 게이트웨이
    "rosy-lowbatt-shutdown.service",  # 목록 밖 전부
])
def test_only_camera_and_navigation_may_be_stopped(forbidden):
    result = subprocess.run(
        [BASH, SCRIPT.as_posix(), "--ab-unit", forbidden, "5"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 2, f"{forbidden} must be refused before any work"
    assert "A/B 불가 단위" in result.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_a_stopped_unit_is_always_restarted():
    text = SCRIPT.read_text(encoding="utf-8")
    stop = text.find("systemctl stop")
    start = text.find("systemctl start", stop)
    assert stop != -1 and start > stop, (
        "the A/B must bring the unit back — a measurement tool never ends "
        "having changed the runtime state"
    )
    assert "2026-09-29-on-demand-activation-measurement-baseline" in text, (
        "the judgment criteria live in the baseline doc; the script must point there"
    )
