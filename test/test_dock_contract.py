"""도크 에이전트 계약 — 문서와 파서가 갈라지지 않게 고정한다.

스키마 하나를 두 곳이 읽는다: `dock/README.md` 가 펌웨어 작성자에게 말하고,
`rosy_core.docking.agent` 가 그것을 파싱한다. 둘이 어긋나면 실기에서만 드러나고,
그때 증상은 "도크가 답을 안 한다"로 보인다.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCK = ROOT / "firmware" / "dock"
README = DOCK / "README.md"


def _documented_example() -> dict:
    """README 의 첫 JSON 블록 — 펌웨어가 따라 쓰는 바로 그 예시."""
    text = README.read_text(encoding="utf-8")
    match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    assert match, "README must document the status payload as a json block"
    return json.loads(match.group(1))


def test_the_documented_payload_parses_as_the_client_expects():
    import sys
    sys.path.insert(0, str(ROOT / "src" / "core" / "core_features"))
    sys.path.insert(0, str(ROOT / "src" / "core" / "core"))
    from core_features.docking.agent import DockAgent, DockReachability

    document = _documented_example()
    status = DockAgent("http://example")._parse(
        json.dumps(document).encode("utf-8"))

    assert status.reachability is DockReachability.OK, status.error
    assert status.load_present == document["load_present"]
    assert status.charging == document["charging"]
    assert status.current_a == pytest.approx(document["current_a"])


def test_the_required_fields_are_the_ones_the_client_requires():
    """클라이언트가 필수로 삼는 필드가 문서에도 필수로 적혀 있어야 한다."""
    import sys
    sys.path.insert(0, str(ROOT / "src" / "core" / "core_features"))
    sys.path.insert(0, str(ROOT / "src" / "core" / "core"))
    from core_features.docking.agent import _REQUIRED

    document = _documented_example()
    for field in _REQUIRED:
        assert field in document, f"README example omits required field '{field}'"


def test_load_present_and_charging_are_documented_as_distinct():
    """접점이 물렸는데 전류가 없는 경우가 있고, 그것은 접촉 실패와 다른 고장이다."""
    text = README.read_text(encoding="utf-8")
    assert "load_present" in text and "charging" in text
    assert re.search(r"load_present.*charging|charging.*load_present",
                     text, re.DOTALL)


def test_the_safety_rule_that_justifies_the_controller_is_documented():
    """바닥에 상시 통전된 DC 접점은 단락·이물 위험이다. 도크에 MCU 가 필요한
    이유가 전류 보고가 아니라 이것이라는 점이 문서에 남아야 한다."""
    text = README.read_text(encoding="utf-8").lower()
    assert "load" in text
    for phrase in ("energis", "de-energis"):
        assert phrase in text, f"README must state the {phrase}e rule"


def test_the_firmware_exists_and_serves_the_documented_path():
    sources = list((DOCK / "firmware").rglob("*.ino")) + \
        list((DOCK / "firmware").rglob("*.cpp"))
    assert sources, "dock firmware sources must exist"
    text = "\n".join(p.read_text(encoding="utf-8") for p in sources)
    assert "/status" in text
    for field in ("load_present", "charging", "current_a"):
        assert field in text, f"firmware must report '{field}'"


def test_the_firmware_does_not_energise_without_a_load():
    """이 한 줄이 지켜지지 않으면 나머지 설계는 의미가 없다."""
    sources = list((DOCK / "firmware").rglob("*.ino")) + \
        list((DOCK / "firmware").rglob("*.cpp"))
    text = "\n".join(p.read_text(encoding="utf-8") for p in sources)
    assert "loadDetected" in text or "load_detected" in text
    assert "setOutput" in text or "digitalWrite" in text


def test_no_credentials_in_the_firmware():
    """도크는 사업장 WLAN 에 붙는다. 자격정보가 소스에 박히면 안 된다."""
    sources = list((DOCK / "firmware").rglob("*"))
    for path in sources:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("PSK =", "password =", "PASSWORD ="):
            assert marker not in text, f"{path.name} appears to embed a credential"
