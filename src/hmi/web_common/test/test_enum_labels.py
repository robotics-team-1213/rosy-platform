"""D-359 US-009 — one Korean word per CORE enum, shared by the dashboard and Fleet.

The maps live in `core_ui_logic.js` because both servers already expose that
file under /common/ (manifest.json), so no bundler or copy is needed.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest

WEB_COMMON = Path(__file__).resolve().parents[1]
SRC = WEB_COMMON.parents[1]
sys.path.insert(0, str(SRC / "contracts" / "foundation" / "core_common"))


def _run(expression: str):
    source = base64.b64encode((WEB_COMMON / "core_ui_logic.js").read_bytes()).decode("ascii")
    script = (f'import * as logic from "data:text/javascript;base64,{source}";\n'
              f"console.log(JSON.stringify({expression}));\n")
    result = subprocess.run(["node", "--input-type=module", "--eval", script],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def _enum(name: str) -> list[str]:
    schemas = pytest.importorskip("protocol.schemas")
    return [member.value for member in getattr(schemas, name)]


@pytest.mark.parametrize(("label_map", "enum"), [
    ("MODE_LABEL", "RobotMode"),
    ("NAVIGATION_LABEL", "NavigationState"),
    ("DOCK_STATE_LABEL", "DockState"),
])
def test_every_protocol_value_has_a_korean_word(label_map, enum):
    labels = _run(f"logic.{label_map}")
    assert sorted(labels) == sorted(_enum(enum))
    assert all(any("가" <= ch <= "힣" for ch in word) for word in labels.values()), labels


def test_mode_words_are_the_sanctioned_ones():
    assert _run("[logic.MODE_LABEL.IDLE, logic.MODE_LABEL.MANUAL, logic.MODE_LABEL.NAVIGATION]") == [
        "대기", "수동", "내비게이션"]


def test_enum_label_shows_an_unknown_value_as_received_and_a_missing_one_as_fallback():
    assert _run("[logic.enumLabel(logic.MODE_LABEL, 'IDLE'), logic.enumLabel(logic.MODE_LABEL, 'NEW_MODE'),"
                " logic.enumLabel(logic.MODE_LABEL, ''), logic.enumLabel(logic.MODE_LABEL, null, '확인 중'),"
                " logic.enumLabel(logic.MODE_LABEL, 'constructor')]") == [
        "대기", "NEW_MODE", "—", "확인 중", "constructor"]
