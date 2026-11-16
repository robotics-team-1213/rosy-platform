"""Calibration jobs API (D-1035): status reads files only, jobs run under the arm lease, incident clear needs measured conditions."""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications/calibration"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import calibration_jobs as jobs_mod  # noqa: E402
import calibration_web as web  # noqa: E402
from test_calibration_web import ORIGIN, Account, call  # noqa: E402

OWNER = "calibration-web:Kim"


class FakeProc:
    pid = os.getpid()

    def __init__(self, log, code=0):
        log.write_text('noise\n{"ok": true}\n', encoding="utf-8")
        self.code = code

    def wait(self):
        return self.code


@pytest.fixture
def cell(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_ARM_LEASES", str(tmp_path / "leases"))
    cal = tmp_path / "cell" / "cal.json"
    cal.parent.mkdir()
    record = {"points": [[0, 0, 0, 0]] * 4, "loo_error_mm": {"max": 3.0, "mean": 1.0}}
    cal.write_text(json.dumps({"sites": {"belt": record}}))
    cal.with_suffix(".bias.json").write_text(json.dumps({"regions": [
        {"site": "belt", "point_m": [0.1, 0.2], "bias_mm": [1, 2], "kind": "visit", "n": 3, "rms_mm": 0.5, "measured": "t"}]}))
    config = cal.parent / "config.json"
    config.write_text(json.dumps({"calibration_path": str(cal), "sites": {"belt": {"surface_z": 0.01}}}))
    cells = tmp_path / "cells.json"
    cells.write_text(json.dumps({"tools": str(ROOT), "python": "py", "work": str(tmp_path / "work"),
                                 "arms": {"arm_b": {"config": str(config), "session": "wrap.sh", "env": {"X": "1"}}}}))
    return cells


@pytest.fixture
def screen(cell):
    calls = {"spawn": [], "clear": [], "session": False}

    def spawn(argv, cwd, env, log):
        calls["spawn"].append((argv, cwd, env))
        return FakeProc(log)

    def tool(argv, timeout=30, env=None):
        if "clear" in argv:
            calls["clear"].append(argv)
        return {"ok": True}, ""

    account = Account()
    server = web.make_server(cell.parent / "store", 0, account, cells=cell, spawn=spawn,
                             probe=lambda arm: calls["session"], incident_tool=tool)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", account, calls, server.RequestHandlerClass.keywords["jobs"], cell
    server.shutdown()
    server.server_close()


def post(url, path, body, origin=ORIGIN):
    status, raw = call(url, path, cookie="valid", origin=origin, body=body, method="POST")
    return status, json.loads(raw)


def test_feature_is_off_without_cells(tmp_path):
    server = web.make_server(tmp_path, 0, Account())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert call(f"http://127.0.0.1:{server.server_port}", "/api/calibration/status", cookie="valid")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_status_reads_files_only(screen):
    url, _, _, _, cell = screen
    status, raw = call(url, "/api/calibration/status", cookie="valid")
    arm = json.loads(raw)["arms"]["arm_b"]
    site = arm["sites"]["belt"]
    assert status == 200 and site["map"]["points"] == 4 and len(site["map"]["sha"]) == 12 and site["surface_z"] == 0.01
    assert site["bias"][0]["kind"] == "visit" and arm["lease"] is None and arm["incident"] == {"ok": True}
    assert call(url, "/api/calibration/status")[0] == 401


def test_job_gates(screen):
    url, account, calls, _, _ = screen
    body = {"arm": "arm_b", "step": "pivot-near", "targets": ["belt:0.1,0.2"], "person_at_switch": True}
    account.operate = False
    assert post(url, "/api/calibration/jobs", body)[0] == 403
    account.operate = True
    assert post(url, "/api/calibration/jobs", body, origin="https://evil.test")[0] == 403
    assert post(url, "/api/calibration/jobs", {**body, "person_at_switch": False})[0] == 422
    assert post(url, "/api/calibration/jobs", {**body, "step": "rebase"})[0] == 422
    assert post(url, "/api/calibration/jobs", {**body, "targets": ["bad"]})[0] == 422
    assert calls["spawn"] == []


def test_job_refused_when_another_owner_holds_the_lease(screen):
    url, _, calls, jobs, _ = screen
    jobs.lease().claim("arm_b", "someone@elsewhere", "hand work", 600, os.getpid(), None)
    status, body = post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "check"})
    assert status == 409 and "someone@elsewhere" in body["error"] and calls["spawn"] == []


def test_job_runs_engine_and_records_result(screen):
    url, _, calls, jobs, _ = screen
    status, job = post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "pivot-near", "targets": ["belt:0.1,0.2"],
                                                      "person_at_switch": True})
    assert status == 202 and job["by"] == "Kim"
    for t in jobs.threads:
        t.join(5)
    argv, cwd, env = calls["spawn"][0]
    assert argv[0] == "wrap.sh" and argv[1] == "py" and argv[2].endswith("cell_calibrate.py") and "auto" in argv
    assert argv[argv.index("--only") + 1] == "pivot-near" and "--person-at-switch" in argv and "--commissioning" in argv
    assert argv[argv.index("--targets") + 1] == "belt:0.1,0.2"
    assert env["ROSY_ARM_LEASE_OWNER"] == OWNER and env["X"] == "1"
    one = json.loads(call(url, f"/api/calibration/jobs/{job['id']}", cookie="valid")[1])
    assert one["status"] == "done" and one["result"] == {"ok": True} and "noise" in one["log_tail"]
    assert json.loads(call(url, "/api/calibration/jobs", cookie="valid")[1])["jobs"][0]["id"] == job["id"]
    assert jobs.lease().status().get("arm_b") is None  # released


def assess(url, verdict="clear"):
    return post(url, "/api/calibration/assessments", {"arm": "arm_b", "verdict": verdict, "reasons": "frames match",
                                                      "evidence": [{"kind": "frame", "ref": "top.png", "sha256": "ab"}]})


def test_assessment_validation(screen):
    url, *_ = screen
    assert post(url, "/api/calibration/assessments", {"arm": "arm_b", "verdict": "maybe"})[0] == 422
    assert assess(url)[0] == 201


def test_clear_needs_fresh_clear_assessment_and_measured_conditions(screen):
    url, _, calls, jobs, cell = screen
    path = "/api/calibration/incidents/arm_b/clear"
    assert post(url, path, {})[0] == 409  # no assessment
    assess(url, "hold")
    assert post(url, path, {})[0] == 409  # newest is hold
    _, row = assess(url)
    calls["session"] = True
    assert post(url, path, {})[0] == 409 and calls["clear"] == []  # session running
    calls["session"] = False
    jobs.lease().claim("arm_b", "someone@elsewhere", "x", 600, os.getpid(), None)
    assert post(url, path, {})[0] == 409  # foreign lease
    jobs.lease().release("arm_b", "someone@elsewhere")
    status, body = post(url, path, {})
    assert status == 200 and body == {"ok": True} and f"ai-assessment {row['id']} by Kim" in calls["clear"][0]
    old = Path(jobs.work / "assessments.jsonl")
    rows = [json.loads(line) for line in old.read_text().splitlines()]
    rows[-1]["at"] = time.time() - 700
    old.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert post(url, path, {})[0] == 409  # stale
