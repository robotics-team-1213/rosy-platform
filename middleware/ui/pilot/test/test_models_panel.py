"""D-423 §3.6: Pilot "모델" panel — read-only status from GET /api/v1/vision/models. Node subprocess."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

PILOT = Path(__file__).resolve().parents[1]
MODULE = PILOT / "models.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const M = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const flush = async () => {{ for (let i = 0; i < 6; i += 1) await Promise.resolve(); }};
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_rows_name_task_slot_revision_and_problems():
    rows = _run_js("""
console.log(JSON.stringify(M.describeModels({tasks: [
  {task: 'object_det', slot: 'active', model_revision: 'object-det-r1', last_error: null, stale: false},
  {task: 'lane_seg', slot: 'shadow', model_revision: null, last_error: 'no shadow model loaded', stale: false},
  {task: 'object_det', slot: 'active', model_revision: 'r2', last_error: null, stale: true},
  null, {slot: 'x'}]})));
""")
    assert rows == [
        {"name": "물체 · 적용", "revision": "object-det-r1", "note": "정상", "problem": False},
        {"name": "차선 · 섀도", "revision": "모델 없음", "note": "no shadow model loaded", "problem": True},
        {"name": "물체 · 적용", "revision": "r2", "note": "보고 끊김", "problem": True},
    ]


def test_poller_reads_only_the_models_endpoint_and_reports_failures_as_null():
    out = _run_js("""
const calls = []; const updates = []; const timers = [];
let reply = {status: 200, body: {tasks: []}};
const poll = M.createModelStatus({
  apiGet: async (path, opts) => { calls.push([path, opts ?? null]); if (reply instanceof Error) throw reply; return reply; },
  onUpdate: (rows) => updates.push(rows),
  schedule: (fn, ms) => { timers.push(ms); return () => {}; },
});
poll.start(); await flush();
reply = {status: 503, body: {}}; poll.stop(); poll.start(); await flush();
reply = new Error('offline'); poll.stop(); poll.start(); await flush();
poll.stop();
console.log(JSON.stringify({calls, updates, timers}));
""")
    assert {c[0] for c in out["calls"]} == {"/api/v1/vision/models"}
    assert all(c[1] is None for c in out["calls"])          # GET only: no method, no body
    assert out["updates"] == [[], None, None]
    assert set(out["timers"]) == {5000}


def test_drive_screen_mounts_the_panel_without_any_model_write():
    drive = (PILOT / "screens" / "drive.js").read_text(encoding="utf-8")
    assert "createModelStatus(" in drive and "models.stop()" in drive
    # Review L10: poll only while the panel is open.
    assert 'modelPanel.addEventListener("toggle"' in drive
    assert "modelPanel.open ? models.start() : models.stop()" in drive
    assert "models.start();" not in drive
    source = MODULE.read_text(encoding="utf-8")
    for word in ("promote", "rollback", "POST", "method"):
        assert word not in source
