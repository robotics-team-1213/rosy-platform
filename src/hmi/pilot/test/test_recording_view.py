"""D-411 A: pure view logic for the robot recording toggle and the recordings sheet (recording.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "recording.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const m = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_the_module_imports_nothing():
    source = MODULE.read_text(encoding="utf-8")
    assert "import " not in source and "fetch(" not in source and "document" not in source


def test_formats():
    out = _run_js("console.log(JSON.stringify([m.formatElapsed(65.4), m.formatElapsed(0), m.formatElapsed(-3), "
                  "m.formatBytes(0), m.formatBytes(999), m.formatBytes(1536), m.formatBytes(12.5e6), "
                  "m.formatBytes(2.25e9)]))")
    assert out == ["1:05", "0:00", "0:00", "0 B", "999 B", "1.5 KB", "12.5 MB", "2.3 GB"]


def test_toggle_view():
    out = _run_js("""console.log(JSON.stringify([
      m.recordingView(null),
      m.recordingView({state: 'idle', elapsed_s: 0, bytes: 0, max_duration_s: 600, last_stop_reason: ''}),
      m.recordingView({state: 'recording', elapsed_s: 65, bytes: 1536, max_duration_s: 600}),
      m.recordingView({state: 'stopping', elapsed_s: 70, bytes: 2048, max_duration_s: 600}),
      m.recordingView({state: 'idle', elapsed_s: 0, bytes: 0, max_duration_s: 600, last_stop_reason: 'max_duration'}),
      m.recordingView({state: 'error', elapsed_s: 0, bytes: 0, max_duration_s: 600, last_stop_reason: ''}),
    ]))""")
    assert out[0] == {"recording": False, "available": False, "busy": False, "label": "로봇 녹화",
                      "detail": "", "reason": "녹화기 응답 없음"}
    assert out[1] == {"recording": False, "available": True, "busy": False, "label": "로봇 녹화",
                      "detail": "", "reason": ""}
    assert out[2]["recording"] is True and out[2]["label"] == "로봇 녹화 중지"
    assert out[2]["detail"] == "녹화 1:05 / 10:00 · 1.5 KB" and out[2]["busy"] is False
    assert out[3]["busy"] is True and out[3]["label"] == "녹화 정리 중"
    assert out[4]["recording"] is False and out[4]["detail"] == "지난 녹화: 10분 상한에서 멈춤"
    assert out[5]["available"] is True and out[5]["detail"] == "녹화기 오류"


def test_error_text_names_every_recording_code():
    out = _run_js("""console.log(JSON.stringify(['RECORDING_BUSY', 'ROBOT_MOVING', 'RECORDER_UNAVAILABLE',
      'RECORDING_QUOTA_FULL', 'RECORDING_DISK_FULL', 'FORBIDDEN', 'RECORDING_NOT_ACTIVE',
      'RECORDING_NOT_FOUND', 'SOMETHING_ELSE', undefined].map((c) => m.errorText(c, 'stop'))))""")
    assert all(out) and len(set(out[:8])) == 8
    assert out[5] == "다른 기기가 시작한 녹화입니다"
    assert out[8] == out[9] == "요청이 거부되었습니다"


def test_sheet_rows_follow_the_download_gate():
    out = _run_js("""console.log(JSON.stringify([
      m.sheetRows({download_allowed: false, download_blocker: 'ROBOT_MOVING', items: [
        {id: 'a', status: 'complete', started_at: '2026-10-02T10:15:00Z', duration_s: 60, bytes: 1000, fetched: false}]}),
      m.sheetRows({download_allowed: true, download_blocker: null, items: [
        {id: 'a', status: 'complete', started_at: '2026-10-02T10:15:00Z', duration_s: 60, bytes: 1000, fetched: true},
        {id: 'b', status: 'incomplete', started_at: '2026-10-02T10:20:00Z', duration_s: null, bytes: 5},
        {id: 'c', status: 'recording', started_at: 'bad', duration_s: null, bytes: 5}]}),
      m.sheetRows({download_allowed: false, download_blocker: 'RECORDING_BUSY', items: []}),
      m.sheetRows(null),
    ]))""")
    assert out[0][0]["canFetch"] is False and out[0][0]["reason"] == "로봇이 멈춘 뒤에 받을 수 있습니다"
    assert out[1][0]["canFetch"] is True and out[1][0]["reason"] == ""
    assert out[1][0]["detail"] == "1:00 · 1.0 KB · 받음"
    assert out[1][1]["canFetch"] is False and out[1][1]["reason"] == "끝나지 않은 녹화입니다"
    assert out[1][1]["detail"] == "— · 5 B"
    assert out[1][2]["reason"] == "녹화 중입니다" and out[1][2]["title"] == "bad"
    assert out[2] == [] and out[3] == []


def test_sheet_notice_names_the_blocker():
    out = _run_js("""console.log(JSON.stringify([
      m.sheetNotice({download_allowed: true, items: [{id: 'a'}]}),
      m.sheetNotice({download_allowed: true, items: []}),
      m.sheetNotice({download_allowed: false, download_blocker: 'RECORDING_BUSY', items: [{id: 'a'}]}),
      m.sheetNotice(null),
    ]))""")
    assert out == ["", "녹화본이 없습니다", "녹화 중에는 받을 수 없습니다", "목록을 불러오지 못했습니다"]


def test_large_recordings_are_left_to_the_pc_tool():
    out = _run_js("""console.log(JSON.stringify([m.PILOT_FETCH_MAX_BYTES,
      m.sheetRows({download_allowed: true, items: [
        {id: 'a', status: 'complete', started_at: 'x', duration_s: 600, bytes: 256e6},
        {id: 'b', status: 'complete', started_at: 'x', duration_s: 600, bytes: 256e6 + 1}]}),
      m.sheetRows({download_allowed: false, download_blocker: 'ROBOT_MOVING', items: [
        {id: 'b', status: 'complete', started_at: 'x', duration_s: 600, bytes: 3e8}]}),
    ]))""")
    assert out[0] == 256e6
    assert out[1][0]["canFetch"] is True
    big = "큰 녹화본은 PC에서 받으세요: rosy_ml fetch <로봇> --http"
    assert out[1][1]["canFetch"] is False and out[1][1]["reason"] == big
    assert out[2][0]["canFetch"] is False and out[2][0]["reason"] == big


def test_forbidden_depends_on_what_was_refused():
    out = _run_js("""console.log(JSON.stringify([m.errorText('FORBIDDEN', 'stop'), m.errorText('FORBIDDEN', 'start'),
      m.errorText('FORBIDDEN', 'fetch'), m.errorText('FORBIDDEN'), m.errorText('ROBOT_MOVING', 'fetch')]))""")
    assert out[0] == "다른 기기가 시작한 녹화입니다"
    assert out[1] == out[2] == out[3] == "운전자(Operator) 권한이 필요합니다"
    assert out[4] == "로봇이 멈춘 뒤에 받을 수 있습니다"