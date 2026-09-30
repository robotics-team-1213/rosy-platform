"""D-321 부록 — calibration.js: 보정 중 표시와 잠금 판정. Node 서브프로세스 패턴."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "calibration.js"

ACTIVITY = {"kind": "CALIBRATING", "session_id": "s1", "calibration_kind": "drive",
            "label": "주행 보정", "owner": {"id": "tok-owner", "role": "operator", "label": "노트북"},
            "started_at": "2026-10-01T09:00:00+00:00", "remaining_s": 24.4}


def _view(activity, my_id):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const C = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
console.log(JSON.stringify(C.calibrationView({json.dumps(activity)}, {json.dumps(my_id)})));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_no_activity_shows_nothing_and_locks_nothing():
    view = _view(None, "tok-owner")
    assert view["active"] is False and view["locked"] is False and view["text"] == ""


def test_other_token_sees_the_banner_and_is_locked_with_a_reason():
    view = _view(ACTIVITY, "tok-viewer")
    assert view["active"] is True
    assert view["locked"] is True
    assert view["text"] == "보정 중 — 주행 보정"
    assert "노트북" in view["reason"] and "비상 정지" in view["reason"]
    assert view["remaining"] == 24


def test_owner_sees_the_banner_but_keeps_control():
    view = _view(ACTIVITY, "tok-owner")
    assert view["active"] is True and view["locked"] is False
    assert view["text"] == "보정 중 — 주행 보정"


def test_unknown_own_id_fails_toward_locked():
    # whoami 가 아직 안 왔으면 남의 보정으로 본다 — 잘못 풀린 조작부보다 잠긴 조작부가 낫다.
    assert _view(ACTIVITY, None)["locked"] is True


def test_other_activity_kinds_are_ignored():
    assert _view({**ACTIVITY, "kind": "SOMETHING_ELSE"}, "x")["active"] is False
