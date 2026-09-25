"""신호등 컨트롤러 계약 — 문서와 펌웨어가 갈라지지 않게 고정한다.

`test_dock_contract.py` 와 같은 자리다. 스키마 하나를 두 곳이 읽는다:
`signal/README.md` 가 펌웨어 작성자와 (향후) Fleet 서버 클라이언트에게 말하고,
`signal/firmware` 가 그것을 구현한다. 둘이 어긋나면 실기에서만 드러나고, 그때
증상은 "신호등이 말을 안 듣는다" 또는 더 나쁘게 "신뢰할 수 없는 표시"로 보인다.

Fleet 서버 쪽 클라이언트는 아직 없다(G-S3). 생기면 독 계약이
`rosy_core.docking.agent` 파서를 대조하듯 이 파일에 클라이언트 파서 대조를
추가한다.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIGNAL = ROOT / "firmware" / "signal"
README = SIGNAL / "README.md"

COMMAND_MODES = {"manual", "cycle", "hold", "all_red", "flash_red"}
STATUS_MODES = COMMAND_MODES | {"failsafe"}


def _json_blocks() -> list:
    """README 의 JSON 블록들 — 첫 블록은 /status 예시여야 한다."""
    text = README.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    assert blocks, "README must document the status payload as a json block"
    return [json.loads(b) for b in blocks]


def _command_examples() -> list:
    return [b for b in _json_blocks() if "mode" in b and "signal_id" not in b]


def _firmware_text() -> str:
    sources = list((SIGNAL / "firmware").rglob("*.ino")) + \
        list((SIGNAL / "firmware").rglob("*.cpp"))
    assert sources, "signal firmware sources must exist"
    return "\n".join(p.read_text(encoding="utf-8") for p in sources)


def test_the_documented_status_example_parses_and_carries_required_fields():
    status = _json_blocks()[0]

    for field in ("signal_id", "mode", "lamps"):
        assert field in status, f"README status example omits '{field}'"
    for lamp in ("red", "yellow", "green"):
        assert lamp in status["lamps"], f"lamps omits '{lamp}'"
    assert status["mode"] in STATUS_MODES, status["mode"]


def test_documented_command_examples_use_the_documented_mode_enum():
    commands = _command_examples()
    assert commands, "README must document at least one /command body"
    for command in commands:
        assert command["mode"] in COMMAND_MODES, command["mode"]


def test_the_firmware_exists_and_serves_the_documented_routes():
    text = _firmware_text()
    assert '"/status"' in text
    assert '"/command"' in text
    for field in ("signal_id", "mode", "lamps", "faults"):
        assert field in text, f"firmware must report '{field}'"


def test_every_declared_firmware_helper_is_defined():
    """The host cannot compile Arduino here, so pin the helper that previously
    existed only as a prototype and would fail at link time."""
    text = _firmware_text()
    assert re.search(r"static const char \*modeName\(Mode m\)\s*\{", text)


def test_the_firmware_boots_into_the_fail_safe_state():
    """이 줄이 무너지면 나머지 설계는 의미가 없다 — 부팅 직후 어떤 램프도
    '살아 있는 신호'처럼 보여서는 안 된다."""
    text = _firmware_text()
    assert "Mode mode = FAILSAFE" in text


def test_the_firmware_falls_back_to_fail_safe_on_supervisor_silence():
    text = _firmware_text()
    assert "HEARTBEAT_TIMEOUT_MS" in text
    assert "enterFailsafe" in text
    assert "supervisor_lost" in text


def test_flash_red_and_all_red_are_documented_as_distinct():
    """점멸(고장 표시)과 점등(명령된 전체 정지)이 합쳐지면 관제 화면이
    '정지시켰다'와 '장비가 말을 안 듣는다'를 구별할 수 없다."""
    text = README.read_text(encoding="utf-8")
    assert "all_red" in text and "flash_red" in text
    assert "failsafe" in text


def test_the_conflict_guard_is_documented_and_implemented():
    """적+녹 동시 점등은 명령 단계에서 거절된다 — EN 12675 충돌 클래스 개념의
    최소 구현."""
    readme = README.read_text(encoding="utf-8")
    assert "conflict" in readme

    text = _firmware_text()
    assert "conflict" in text
    assert re.search(r"red.{0,40}green|green.{0,40}red", text, re.DOTALL), \
        "firmware must reference red and green together in the guard"


def test_commands_require_a_token_and_fail_closed():
    text = _firmware_text()
    assert "X-Rosy-Token" in text
    assert "403" in text
    # 토큰이 없는(미규정) 장치는 fail-closed — 명령 경로가 열려 있으면 안 된다.
    assert "authToken.length() == 0" in text


def test_serial_wifi_provisioning_splits_ssid_from_the_key():
    text = _firmware_text()
    assert 'const int wifiSep = rest.indexOf(\' \');' in text
    assert 'ssid = rest.substring(0, wifiSep)' in text
    assert 'key = rest.substring(wifiSep + 1)' in text


def test_stale_commands_are_rejected_by_sequence():
    text = _firmware_text()
    assert "stale_seq" in text
    assert "lastSeq" in text


def test_the_firmware_stores_no_lamp_state_to_resurrect():
    """재부팅 뒤 오래된 명령이 혼자 되살아나는 경로를 원천 차단한다 — NVS 에
    램프 상태를 저장하지 않는다는 것이 계약이다."""
    readme = README.read_text(encoding="utf-8")
    assert re.search(r"NVS 에 저장하지 않|저장하지 않는다", readme)
    text = _firmware_text()
    for marker in ("putBool", "putLamp", "saveLamp"):
        assert marker not in text, f"firmware must not persist lamp state ({marker})"


def test_no_credentials_in_the_sources():
    """신호등은 사업장 WLAN 에 붙는다. 자격정보가 소스에 박히면 안 된다."""
    for path in SIGNAL.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("PSK =", "password =", "PASSWORD ="):
            assert marker not in text, f"{path.name} appears to embed a credential"


def test_the_firmware_does_not_initiate_connections():
    """독과 같은 방향 규칙: 장치는 서버다. 클라이언트 소켓을 여는 코드가
    스며들면 방향이 뒤집힌다."""
    text = _firmware_text()
    for marker in ("HTTPClient", "wifi_client", "WiFiClient("):
        assert marker not in text, f"firmware must not open client connections ({marker})"
