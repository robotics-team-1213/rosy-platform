"""D-975 설치 노선: 역 상태는 서버 근거로만 정하고, 읽지 못한 역을 완료로 그리지 않는다."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "applications/fleet/web/installation/install-line.js"
PAGE = ROOT / "applications/fleet/web/installation/install.html"


def _states(results):
    source = base64.b64encode(MODULE.read_bytes()).decode("ascii")
    script = (f'import * as line from "data:text/javascript;base64,{source}";\n'
              f"console.log(JSON.stringify(line.stationStates({json.dumps(results)})));\n")
    done = subprocess.run(["node", "--input-type=module", "--eval", script],
                          check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(done.stdout)


def ok(body):
    return {"ok": True, "body": body}


def test_the_first_unfinished_station_is_now_and_the_rest_wait():
    states = _states([ok({"robots": [{"robot_id": "pinky-01"}]}), ok({"credentials": []}),
                      ok({"calibrations": []}), ok({"start_points": []})])
    assert [row["state"] for row in states] == ["done", "now", "todo", "todo"]
    assert states[0]["note"] == "1대"


def test_revoked_cameras_and_invalid_start_points_do_not_count():
    states = _states([ok({"robots": [{}]}), ok({"credentials": [{"state": "revoked"}]}),
                      ok({"calibrations": [{"source_id": "cam-top"}]}),
                      ok({"start_points": [{"valid": False}]})])
    assert [row["state"] for row in states] == ["done", "now", "done", "todo"]
    assert states[3]["note"] == "없음"


def test_an_unread_source_is_never_drawn_as_done():
    states = _states([{"ok": False}, ok({"credentials": [{"state": "active"}]}),
                      {"ok": False}, ok({"start_points": [{"valid": True}]})])
    assert states[0] == {"state": "todo", "note": "확인 못 함"}
    assert states[2] == {"state": "todo", "note": "확인 못 함"}
    assert [row["state"] for row in states] == ["todo", "done", "todo", "done"]


def test_all_done_leaves_no_current_station():
    states = _states([ok({"robots": [{}]}), ok({"credentials": [{"state": "active"}]}),
                      ok({"calibrations": [{}]}), ok({"start_points": [{"valid": True}]})])
    assert {row["state"] for row in states} == {"done"}


def test_the_page_mounts_one_fleet_line_with_the_stage_sheet():
    page = PAGE.read_text(encoding="utf-8")
    assert '<ol id="install-line" class="ui-stage-track" data-line="fleet"' in page
    assert '/common/stage-strip.css' in page
    assert page.count('id="install-line"') == 1


def test_station_links_name_install_tasks_the_page_can_open():
    """역 링크는 작업 선택기가 여는 작업 id여야 한다 — 숨은 패널 앵커는 눌러도 아무 일이 없다."""
    import re
    web = ROOT / "applications" / "fleet" / "web"
    page = (web / "installation" / "install.js").read_text(encoding="utf-8")
    tasks = set(re.findall(r'\{id: "([a-z-]+)", title:', page))
    anchors = set(re.findall(r'anchor: "#([a-z-]+)"', (web / "installation" / "install-line.js").read_text(encoding="utf-8")))
    assert anchors and anchors <= tasks, anchors - tasks
    assert 'addEventListener("hashchange"' in page
