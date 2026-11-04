"""D-975 Cell 준비 노선: 응답이 채운 사실만 완료로 그린다."""

import json
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web" / "cell"


def states(facts):
    script = f"""import {{cellLineStates}} from {json.dumps((WEB / 'cell-line.js').as_uri())};
console.log(JSON.stringify(cellLineStates({json.dumps(facts)})));"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_first_unfinished_station_is_current():
    got = states({"recipe": True, "cell": False, "plan": False, "proposal": False, "job": None})
    assert [s["state"] for s in got] == ["done", "now", "todo", "todo", "todo"]
    assert got[0]["note"] == "저장됨" and got[4]["note"] == "작업 조회 전"


def test_a_read_job_counts_as_proposed_and_only_confirmed_goal_finishes():
    base = {"recipe": True, "cell": True, "plan": True, "proposal": False}
    running = states({**base, "job": {"status": "RUNNING"}, "jobNote": "실행 중"})
    assert [s["state"] for s in running] == ["done", "done", "done", "done", "now"]
    assert running[4]["note"] == "실행 중"
    assert states({**base, "job": {"status": "GOAL_CONFIRMED"}})[4]["state"] == "done"


def test_hold_with_a_reason_is_blocked_and_nothing_is_current_after_finish():
    base = {"recipe": True, "cell": True, "plan": True, "proposal": True}
    assert states({**base, "job": {"status": "HOLD", "reason": "SITE_AUTHORITY_CHANGED"}})[4]["state"] == "blocked"
    assert all(s["state"] == "done" for s in states({**base, "job": {"status": "GOAL_CONFIRMED"}}))


def test_page_mounts_the_line_without_new_requests():
    html = (WEB / "cell.html").read_text(encoding="utf-8")
    assert '<ol id="cell-line" class="ui-stage-track" data-line="fleet"' in html
    assert '/common/stage-strip.css' in html
    assert "/api/" not in (WEB / "cell-line.js").read_text(encoding="utf-8")
