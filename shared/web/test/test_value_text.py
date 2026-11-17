"""C4 valueText: an unknown value is EVIDENCE_LABEL.unavailable, never 0, 100%, 정상 or undefined (D-280)."""

import json
from pathlib import Path
import subprocess

MODULE = (Path(__file__).resolve().parents[1] / "value-text.js").as_uri()


def _run(expression: str):
    script = f'import * as v from "{MODULE}";\nconsole.log(JSON.stringify({expression}));\n'
    result = subprocess.run(["node", "--input-type=module", "--eval", script],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def test_unknown_values_are_unavailable_never_a_default():
    unknown = {"text": "정보 없음", "state": "unavailable"}
    for raw in ("undefined", "null", '""', '"  "', "NaN", "Infinity"):
        assert _run(f"v.valueText({raw}, {{unit: '%'}})") == unknown, raw
    assert _run("v.valueText(1, {evidence: 'unavailable'})") == unknown
    assert _run("v.valueText(1, {evidence: 'disconnected'})") == {"text": "연결 끊김", "state": "disconnected"}


def test_known_zero_is_zero_and_stale_carries_its_age():
    assert _run("v.valueText(0, {unit: '%'})") == {"text": "0%", "state": "fresh"}
    assert _run("v.valueText(1.234, {digits: 1, unit: ' mm'})") == {"text": "1.2 mm", "state": "fresh"}
    assert _run("v.valueText(42, {unit: '%', age: 12})") == {"text": "42% · 12초 전", "state": "delayed"}
    assert _run("v.valueText(42, {evidence: 'delayed'})") == {"text": "42", "state": "delayed"}
