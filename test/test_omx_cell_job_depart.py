"""arm_s cell_policy_drive -> Fleet R Pinky depart only after a real took_one (2026-11-26 decision)."""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402
import cell_job_depart as depart  # noqa: E402

PARAMS = {
    "arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json", "max_chunks": 4, "operator": "op_a",
    "mode": "act", "policy_root": "models/p", "policy_revision": "a" * 64, "cell_calibration": "cal/s.json",
    "model_calibration": "cal/m.json", "person_at_switch": True, "depart_robot": "rosy_46",
}


class _Proc:
    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code


def _run(tmp_path, monkeypatch, result, *, exit_code=0, post=None, **extra):
    for n in ("cell-s.json", "chunks-s.json"):
        (tmp_path / n).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/x/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **kw: _Proc(None))
    monkeypatch.setattr(api, "_session_lock_held", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(depart, "post_depart", lambda *a, **kw: calls.append((a, kw)) or (post or {"sent": True, "http_status": 200}))
    runner = api.Runner(tmp_path, incident_check_fn=lambda a: None, fleet_safety_check_fn=lambda a: {"online": False, "blocked": False},
                        fleet_r_url="https://fleet.example:8443", fleet_token_file=tmp_path / "tok")
    res = runner.start("cell_policy_drive", {**PARAMS, **extra})
    assert res["code"] == 202, res
    run = runner.runs[res["id"]]
    run["log"].write_text(json.dumps(result) + "\n", encoding="utf-8")
    run["proc"].code = exit_code
    return runner.get(res["id"]), calls, runner, res["id"]


def test_took_one_posts_once_with_body(tmp_path, monkeypatch):
    info, calls, runner, jid = _run(tmp_path, monkeypatch, {"result": "ok", "took_one": True})
    runner.get(jid)  # a second poll must not send again
    assert len(calls) == 1
    assert calls[0][0][:3] == ("rosy_46", "depart_s1", f"depart-{jid}")
    assert info["structured_result"]["took_one"] is True and info["structured_result"]["depart"]["http_status"] == 200
    rows = [json.loads(x) for x in (tmp_path / "cell-job-api" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r for r in rows if r.get("event") == "depart"][0]["http_status"] == 200


@pytest.mark.parametrize(("result", "exit_code", "extra", "why"), [
    ({"took_one": False, "reason": "gripper empty"}, 0, {}, "gripper empty"),
    ({"took_one": True}, 3, {}, "job exit 3"),
    ({"took_one": True}, 0, {"dry_run": True}, "dry_run"),
])
def test_no_post_and_reason_recorded(tmp_path, monkeypatch, result, exit_code, extra, why):
    info, calls, *_ = _run(tmp_path, monkeypatch, result, exit_code=exit_code, **extra)
    assert calls == []
    d = info["structured_result"]["depart"]
    assert d["sent"] is False and why in d["reason"]


def test_fleet_exception_keeps_arm_result(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fleet down")

    info, _, runner, jid = _run(tmp_path, monkeypatch, {"took_one": True})
    run = runner.runs[jid]
    run["depart"] = None
    monkeypatch.setattr(depart, "post_depart", boom)
    assert depart.depart_once(runner, jid, run)["sent"] is False
    assert info["exit"] == 0 and info["structured_result"]["took_one"] is True


def test_skip_reason_unit():
    base = {"job": "cell_policy_drive", "params": PARAMS, "exit_code": 0, "result": {"took_one": True}}
    assert depart.depart_skip_reason(**base) is None
    assert "only for arm_s" in depart.depart_skip_reason(**{**base, "params": {**PARAMS, "arm": "arm_b"}})
    assert depart.depart_skip_reason(**{**base, "params": {"arm": "arm_s"}}) == "depart not requested"
    assert depart.depart_skip_reason(**{**base, "result": None}) == "no structured result"


def test_post_depart_body_and_fleet_errors(tmp_path):
    tok = tmp_path / "tok"
    tok.write_text("secret\n", encoding="utf-8")
    seen = {}

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b'{"ok": true}'

    def ok(req, context, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), auth=req.get_header("Authorization"))
        return Resp()

    r = depart.post_depart("rosy_46", "depart_s1", "t1", fleet_r_url="https://f:8443", token_file=tok, urlopen_fn=ok)
    assert r["sent"] and r["http_status"] == 200
    assert seen == {"url": "https://f:8443/api/fleet/pipeline/pinky-tasks",
                    "body": {"robot_id": "rosy_46", "action": "depart_s1", "task_id": "t1"}, "auth": "Bearer secret"}

    def refuse(req, context, timeout):
        raise HTTPError(req.full_url, 403, "no", {}, BytesIO(b'{"detail":{"code":"FORBIDDEN"}}'))

    r = depart.post_depart("rosy_46", "depart_s1", "t1", fleet_r_url="https://f:8443", token_file=tok, urlopen_fn=refuse)
    assert r["http_status"] == 403 and "FORBIDDEN" in r["reason"]

    def down(req, context, timeout):
        raise OSError("unreachable")

    r = depart.post_depart("rosy_46", "depart_s1", "t1", fleet_r_url="https://f:8443", token_file=tok, urlopen_fn=down)
    assert r["sent"] is False and "unreachable" in r["reason"]
    assert depart.post_depart("r", "depart_s1", "t", fleet_r_url=None, token_file=None)["sent"] is False
    assert depart.post_depart("r", "depart_s1", "t", fleet_r_url="http://f", token_file=tok)["sent"] is False
