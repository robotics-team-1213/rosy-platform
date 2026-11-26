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

OWNER = "calibration-web:acct-1"  # the account id, not the display name


class FakeProc:
    pid = os.getpid()

    def __init__(self, log, code=0):
        log.write_text('noise\n{"ok": true}\n', encoding="utf-8")
        self.code = code

    def wait(self, timeout=None):
        return self.code

    def terminate(self):
        pass


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
    config.write_text(json.dumps({"arm_id": "arm_b", "calibration_path": str(cal), "sites": {"belt": {"surface_z": 0.01, "place": [.2, .2], "yaw_deg": 0},
                                 "floor": {"surface_z": 0.02, "place": [0.1, -0.2], "yaw_deg": 15}}}))
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


def test_route_check_binds_the_executor_config_and_arm_scoped_slots(screen):
    url, _, calls, jobs, cell = screen
    route = ["tmp-b-2-l1", "ship-h1r2-l0"]
    body = {"arm": "arm_b", "step": "check", "route": route, "task_id": "fleet:route-12"}
    endpoint = "/api/calibration/jobs"
    assert post(url, endpoint, body)[0] == 409  # never fall back to the calibration stack config
    cfg = cell.parent / "route.json"
    jobs.arms["arm_b"]["route_config"] = str(cfg)
    cfg.write_text(json.dumps({"arm_id": "arm_a"}))
    assert post(url, endpoint, body)[0] == 422
    cfg.write_text(json.dumps({"arm_id": "arm_b"}))
    assert post(url, endpoint, {**body, "route": ["tmp-a-1-l1", route[1]]})[0] == 422
    assert post(url, endpoint, {**body, "step": "remap", "person_at_switch": True})[0] == 422
    assert post(url, endpoint, {**body, "task_id": "../wrong"})[0] == 422
    assert not calls["spawn"]
    status, job = post(url, endpoint, body)
    assert status == 202 and job["route"] == route and job["route_config"] == cfg.name
    assert job["task_id"] == body["task_id"]
    argv, cwd, _ = calls["spawn"][0]
    assert argv == ["py", jobs.engine("cell_calibrate.py"), "--config", str(cfg), "check", "--route", *route]
    assert cwd == str(cfg.parent)
    for thread in jobs.threads:
        thread.join()


def test_supply_check_binds_its_own_profile_targets_and_provenance(screen):
    url, _, calls, jobs, cell = screen
    path = cell.parent / "supply.json"
    config = {"arm_id": "arm_s", "sites": {"pinky": {"place": [0.2, 0.1]}, "belt": {}}}
    path.write_text(json.dumps(config))
    jobs.arms["arm_s"] = {"config": str(path)}
    body = {"arm": "arm_s", "step": "check", "supply_route": True}
    endpoint = "/api/calibration/jobs"
    assert post(url, endpoint, {**body, "arm": "arm_b"})[0] == 422
    assert post(url, endpoint, {**body, "targets": ["pinky:1,2"]})[0] == 422
    status, missing = post(url, endpoint, body)
    assert status == 422 and "belt" in missing["error"] and not calls["spawn"]
    config["sites"]["belt"]["place"] = [0.1, -0.1]
    path.write_text(json.dumps(config))
    status, job = post(url, endpoint, body)
    assert status == 202 and job["supply_route"] and job["route_config"] == path.name
    assert job["targets"] == ["pinky:0.2,0.1", "belt:0.1,-0.1"] and "route" not in job
    assert calls["spawn"][0][0][-4:] == ["check", "--targets", *job["targets"]]
    for thread in jobs.threads:
        thread.join()


def test_fleet_link_uses_only_operator_configured_https(cell):
    conf = json.loads(cell.read_text())
    for url, expected in [("https://fleet.example/cell", True), ("http://fleet.example/cell", False),
                          ("javascript:alert(1)", False), ("https://user:pw@fleet.example/", False)]:
        cell.write_text(json.dumps({**conf, "fleet_cell_console_url": url}))
        assert jobs_mod.Jobs(cell).fleet_console_url == (url if expected else None)


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


def test_one_job_per_arm(screen):
    url, _, calls, jobs, _ = screen
    (jobs.work / "jobs").mkdir(parents=True, exist_ok=True)
    jobs.write({"id": "20261117T020000-abcdef", "arm": "arm_b", "status": "running", "pid": os.getpid(),
                "started": "2026-11-17T02:00:00Z"})
    status, body = post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "check"})
    assert status == 409 and "20261117T020000-abcdef" in body["error"] and calls["spawn"] == []


def test_a_failed_record_write_stops_the_engine_and_frees_the_lease(screen, monkeypatch):
    url, _, calls, jobs, _ = screen
    stopped = []
    monkeypatch.setattr(FakeProc, "terminate", lambda self: stopped.append("terminate"), raising=False)
    monkeypatch.setattr(jobs, "write", lambda record: (_ for _ in ()).throw(OSError("disk full")))
    status, _ = post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "check"})
    assert status == 500 and stopped == ["terminate"] and jobs.lease().status().get("arm_b") is None


def test_a_remap_can_be_asked_to_remeasure_a_current_map(screen):
    url, _, calls, jobs, _ = screen
    status, job = post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "remap", "remeasure": True, "person_at_switch": True})
    assert status == 202
    for t in jobs.threads:
        t.join(5)
    argv = calls["spawn"][0][0]
    assert "--remeasure-map" in argv and argv[argv.index("--only") + 1] == "remap" and "--person-at-switch" in argv
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "check", "remeasure": True})[0] == 422
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "remap", "remeasure": 1, "person_at_switch": True})[0] == 422


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
    assert env["ROSY_ARM_LEASE_OWNER"] == f"{OWNER}:{job['id']}" and env["X"] == "1"
    one = json.loads(call(url, f"/api/calibration/jobs/{job['id']}", cookie="valid")[1])
    assert one["status"] == "done" and one["result"] == {"ok": True} and "noise" in one["log_tail"]
    assert json.loads(call(url, "/api/calibration/jobs", cookie="valid")[1])["jobs"][0]["id"] == job["id"]
    assert jobs.lease().status().get("arm_b") is None  # released


def test_a_failed_job_carries_the_engine_exit_message(cell, monkeypatch):
    """2026-11-26: a failed remap showed only "실패"; its reason was the log's last, non-JSON line."""
    jobs = jobs_mod.Jobs(cell)
    finishers = []
    monkeypatch.setattr(jobs_mod.threading.Thread, "start", lambda thread: finishers.append(thread))

    def spawn(argv, cwd, env, log):
        log.write_text('{"point": [0.11, 0.04], "stopped": "goto above_pick"}\n{"jaw_labels": null}\n'
                       'remap stopped at goto above_pick for [0.11, 0.04]: contact; remap: only 0 marks agree of 0\n',
                       encoding="utf-8")
        proc = FakeProc.__new__(FakeProc)
        proc.code = 1
        return proc

    jobs.spawn = spawn
    status, job = jobs.start({"arm": "arm_b", "step": "check"}, "Kim", "acct-1")
    assert status == 202
    for thread in finishers:
        thread.run()
    one = jobs.job(job["id"])
    assert one["status"] == "failed" and one["error"].startswith("remap stopped at goto above_pick")
    assert one["result"] == {"jaw_labels": None}


def test_late_same_account_finish_leaves_new_job_lease(cell, monkeypatch):
    jobs = jobs_mod.Jobs(cell)
    lease = jobs.lease()
    completed = []
    monkeypatch.setattr(jobs_mod.threading.Thread, "start", lambda thread: completed.append(thread))
    jobs.spawn = lambda argv, cwd, env, log: FakeProc(log)
    body = {"arm": "arm_b", "step": "check"}
    assert (first := jobs.start(body, "Kim", "acct-1"))[0] == 202
    old = first[1]
    # Worker exited, the terminal record is durable, but its final release is delayed.
    jobs.write({**old, "status": "done"})
    monkeypatch.setattr(lease, "_pid_alive", lambda pid: False)
    assert (second := jobs.start(body, "Kim", "acct-1"))[0] == 202
    monkeypatch.setattr(lease, "_pid_alive", lambda pid: True)
    completed[0].run()
    assert old["lease_owner"] != second[1]["lease_owner"]
    assert lease.status()["arm_b"]["owner"] == second[1]["lease_owner"]
    completed[1].run()
    assert "arm_b" not in lease.status()


def test_spawn_failure_cannot_free_a_replacement_by_same_account(cell):
    jobs = jobs_mod.Jobs(cell)
    lease = jobs.lease()
    other = f"{OWNER}:20261117T020001-111111"

    def failed(argv, cwd, env, log):
        assert lease.release("arm_b", env["ROSY_ARM_LEASE_OWNER"])
        lease.claim("arm_b", other, "replacement", 600, os.getpid())
        raise OSError("spawn failed")

    jobs.spawn = failed
    assert jobs.start({"arm": "arm_b", "step": "check"}, "Kim", "acct-1")[0] == 500
    assert lease.status()["arm_b"]["owner"] == other


@pytest.mark.parametrize("condition", ["dead", "reused_pid", "legacy_dead"])
def test_restart_projects_worker_with_unknown_outcome_and_allows_new_job(cell, monkeypatch, condition):
    jobs = jobs_mod.Jobs(cell, spawn=lambda argv, cwd, env, log: FakeProc(log))
    arm, old_id = "arm_b", "20261117T020000-abcdef"
    pid = os.getpid() if condition == "reused_pid" else 99999999
    owner = f"{OWNER}:{old_id}"
    row = {"id": old_id, "arm": arm, "pid": pid, "status": "running"}
    if condition != "legacy_dead":
        row.update(lease_owner=owner, pid_start_ticks=1)
        jobs.lease().claim(arm, owner, "old run", 600, pid)
    monkeypatch.setattr(jobs_mod, "process_stamp", lambda pid: 2 if pid == os.getpid() else None)
    jobs.job_file(old_id).parent.mkdir(parents=True)
    jobs.write(row)
    assert jobs.job(old_id)["status"] == jobs.jobs()[0]["status"] == "interrupted"
    assert "exit_code" not in jobs.job(old_id) and "result" not in jobs.job(old_id)
    assert jobs.start({"arm": arm, "step": "check"}, "Kim", "acct-1")[0] == 202
    for t in jobs.threads:
        t.join(5)


def test_map_grade_requires_measured_box_plane_geometry():
    record = {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "measured": "2026-11-26", "loo_error_mm": {"mean": 1, "max": 2},
              "points": [{"pixel": [i, 5], "arm_m": [0, i]} for i in range(5)]}
    assert jobs_mod.map_grade("floor", record) == "fine"
    assert jobs_mod.map_grade("floor", {**record, "z_view": 0.08}) == "coarse"
    assert jobs_mod.map_grade("floor~coarse", record) == "coarse"
    assert jobs_mod.map_grade("floor", {"homography": record["homography"]}) == "unknown"
    assert jobs_mod.map_grade("floor", {**record, "homography": [True]}) == "unknown"


def evidence(jobs):
    import hashlib

    root = jobs.work / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind, name, data in (("frame", "top.jpg", b"jpeg"), ("joints", "joints.json", b'{"state": [0, -58]}')):
        (root / name).write_bytes(data)
        rows.append({"kind": kind, "ref": name, "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def assess(url, jobs, verdict="clear", rows=None):
    return post(url, "/api/calibration/assessments", {"arm": "arm_b", "verdict": verdict, "reasons": "frames match",
                                                      "model": "claude-opus", "evidence": rows or evidence(jobs)})


def test_assessment_validation(screen):
    url, _, _, jobs, _ = screen
    assert post(url, "/api/calibration/assessments", {"arm": "arm_b", "verdict": "maybe"})[0] == 422
    assert assess(url, jobs)[0] == 201
    rows = evidence(jobs)
    assert assess(url, jobs, rows=[{**rows[0], "sha256": "00"}, rows[1]])[0] == 422  # hash does not match the file
    assert assess(url, jobs, rows=rows[:1])[0] == 422  # a frame alone: joints are required too
    assert assess(url, jobs, rows=[{**rows[0], "ref": "../../cells.json"}, rows[1]])[0] == 422  # outside evidence/
    no_model = {"arm": "arm_b", "verdict": "clear", "reasons": "r", "evidence": rows}
    assert post(url, "/api/calibration/assessments", no_model)[0] == 422


def test_clear_needs_fresh_clear_assessment_and_measured_conditions(screen):
    url, _, calls, jobs, cell = screen
    path = "/api/calibration/incidents/arm_b/clear"
    assert post(url, path, {})[0] == 409  # no assessment
    assess(url, jobs, "hold")
    assert post(url, path, {})[0] == 409  # newest is hold
    _, row = assess(url, jobs)
    calls["session"] = True
    assert post(url, path, {})[0] == 409 and calls["clear"] == []  # session running
    calls["session"] = False
    jobs.lease().claim("arm_b", "someone@elsewhere", "x", 600, os.getpid(), None)
    assert post(url, path, {})[0] == 409  # foreign lease
    jobs.lease().release("arm_b", "someone@elsewhere")
    jobs.lease().claim("arm_b", OWNER, "calibration pivot-near", 600, os.getpid(), None)
    assert post(url, path, {})[0] == 409 and calls["clear"] == []  # the clearer's own job is still moving the arm
    jobs.lease().release("arm_b", OWNER)
    status, body = post(url, path, {})
    assert status == 200 and body == {"ok": True} and f"ai-assessment {row['id']} by Kim" in calls["clear"][0]
    old = Path(jobs.work / "assessments.jsonl")
    rows = [json.loads(line) for line in old.read_text().splitlines()]
    rows[-1]["at"] = time.time() - 700
    old.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert post(url, path, {})[0] == 409  # stale


def test_surface_step_requires_person_at_switch_and_service_passes_cells(screen):
    url, _, calls, jobs, _ = screen
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "surface", "person_at_switch": False})[0] == 422
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "surface", "person_at_switch": True})[0] == 422
    assert calls["spawn"] == []
    unit = (ROOT / "applications/calibration/rosy-calibration-web.service").read_text(encoding="utf-8")
    assert "--cells %h/.config/rosy/calibration/cells.json" in unit


def test_repeat_surface_uses_named_registered_target(screen):
    url, _, calls, jobs, _ = screen
    body = {"arm": "arm_b", "step": "surface", "site": "floor", "person_at_switch": True, "surface_clear": True}
    sites = jobs.status()["arms"]["arm_b"]["sites"]
    assert sites["floor"]["place_xy_m"] == [0.1, -0.2] and sites["floor"]["can_remeasure_surface"]
    assert not sites["belt"]["can_remeasure_surface"]
    for invalid in ({"site": "../floor"}, {"site": "belt"}, {"site": []}, {"step": "remap"},
                    {"targets": ["belt:1,2"]}, {"person_at_switch": False}, {"surface_clear": False}):
        assert post(url, "/api/calibration/jobs", {**body, **invalid})[0] == 422
    assert not calls["spawn"]
    status, job = post(url, "/api/calibration/jobs", body)
    assert status == 202 and job["site"] == "floor"
    for t in jobs.threads:
        t.join(5)
    argv = calls["spawn"][0][0]
    assert argv[0] == "wrap.sh" and argv[argv.index("--remeasure-surface") + 1] == "floor" and "--surface-clear" in argv
    assert argv[argv.index("--only") + 1] == "surface" and "--commissioning" in argv and "--person-at-switch" in argv


def test_post_eval_uses_one_registered_point_and_existing_movement_guards(screen):
    url, _, calls, jobs, _ = screen
    body = {"arm": "arm_b", "step": "post-eval", "site": "floor", "person_at_switch": True}
    sites = jobs.status()["arms"]["arm_b"]["sites"]
    assert sites["floor"]["can_post_eval"]
    for extra in ({"site": None}, {"site": "missing"}, {"person_at_switch": False}, {"targets": []},
                  {"targets": ["floor:0,0"]}, {"apply": True}, {"x": 0.3}):
        assert post(url, "/api/calibration/jobs", {**body, **extra})[0] == 422
    jobs.lease().claim("arm_b", "foreign", "manual", 600, os.getpid(), None)
    assert post(url, "/api/calibration/jobs", body)[0] == 409
    jobs.lease().release("arm_b", "foreign")
    assert not calls["spawn"]
    status, job = post(url, "/api/calibration/jobs", body)
    assert status == 202 and job["site"] == "floor" and "surface_clear" not in job
    assert job["targets"] == ["floor:0.1,-0.2"]
    for thread in jobs.threads:
        thread.join(5)
    assert calls["spawn"][0][0] == [
        "wrap.sh", "py", jobs.engine("cell_post_eval.py"), "--config", str(jobs.arm_config("arm_b")[0]),
        "--targets", "floor:0.1,-0.2", "--commissioning", "--person-at-switch",
    ]


@pytest.mark.parametrize(("step", "targets", "arm", "route", "use_policy"), [
    ("check", [], "arm_b", ["tmp-b-2-l1", "ship-h1r2-l0"], True),
    ("check", ["floor:0.1,-0.2"], "arm_b", ["tmp-b-2-l1", "ship-h1r2-l0"], False),
    ("check", [], "arm_a", ["tmp-b-2-l1", "ship-h1r2-l0"], False),
    ("check", [], "arm_b", None, False), ("check", [], "arm_b", True, False),
    ("depth-verify", [], "arm_b", ["tmp-b-2-l1", "ship-h1r2-l0"], False),
])
def test_only_generic_check_uses_enabled_same_arm_route_profile(screen, step, targets, arm, route, use_policy):
    url, _, calls, jobs, cells = screen
    stack_path = jobs.arm_config("arm_b")[0]
    policy_path = cells.parent / "policy.json"
    policy_path.write_text(json.dumps({"arm_id": arm, "preflight": {"check_route": route}}))
    jobs.arms["arm_b"]["route_config"] = str(policy_path)
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": step, "targets": targets})[0] == 202
    for thread in jobs.threads:
        thread.join(5)
    argv, cwd, _ = calls["spawn"][0]
    expected = policy_path if use_policy else stack_path
    assert argv[argv.index("--config") + 1] == str(expected) and cwd == str(expected.parent)


@pytest.mark.parametrize(("name", "entry", "arm"), [
    ("floor", {"start": [0.1, -0.2]}, "arm_b"), ("floor", {"place": [True, -0.2]}, "arm_b"),
    ("floor", {"place": [0.2, float("nan")]}, "arm_b"), ("floor", {"place": [0.2]}, "arm_b"),
    ("stand:r1-s1", {"place": [0.1, -0.2]}, "arm_b"),
    ("tmp-a-1-l1", {"place": [0.1, -0.2]}, "arm_b"),
    ("floor", {"place": [0.1, -0.2]}, "arm_a"),
])
def test_post_eval_ineligible_points_hidden_and_refused(cell, name, entry, arm):
    jobs = jobs_mod.Jobs(cell, spawn=lambda *args: pytest.fail("ineligible job started"),
                         incident_tool=lambda *args: ({}, ""))
    path, config = jobs.arm_config("arm_b")
    config.update(arm_id=arm, sites={name: entry})
    path.write_text(json.dumps(config))
    assert not jobs.status()["arms"]["arm_b"]["sites"][name]["can_post_eval"]
    assert jobs.start({"arm": "arm_b", "step": "post-eval", "site": name, "person_at_switch": True}, "operator")[0] == 422


@pytest.mark.parametrize("geometry", [{"moves": True}, {"on_vehicle": "pinky"}, {"moving_px": [0, 10]},
                                      {"tier_of": "floor"}, {"tier": 2}, {"layers_below": 1}, {"layer": 1}, {"z_offset_m": .03}])
def test_mobile_or_elevated_board_is_ineligible_in_form_api_and_engine(screen, geometry):
    import cell_surface

    url, _, calls, jobs, _ = screen
    path, config = jobs.arm_config("arm_b")
    config["sites"]["board"] = {**config["sites"]["floor"], **geometry}
    path.write_text(json.dumps(config))
    assert not jobs.status()["arms"]["arm_b"]["sites"]["board"]["can_remeasure_surface"]
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": "surface", "site": "board",
                                               "person_at_switch": True, "surface_clear": True})[0] == 422
    assert not calls["spawn"]
    assert cell_surface.surface_selection_error(config, {}, {}, "board") == "registered fixed surface site required"


@pytest.mark.parametrize("step", ["check", "depth-verify"])
def test_read_only_job_never_starts_an_arm_session(screen, step):
    url, _, calls, jobs, _ = screen
    assert post(url, "/api/calibration/jobs", {"arm": "arm_b", "step": step})[0] == 202
    for t in jobs.threads:
        t.join(5)
    assert calls["spawn"][0][0][0] == "py"


def test_missing_or_malformed_cells_keeps_requests_online_and_status_404(tmp_path):
    bad = tmp_path / "bad-cells.json"
    bad.write_text("{not json", encoding="utf-8")
    for cells in (tmp_path / "missing-cells.json", bad):
        server = web.make_server(tmp_path / "store", 0, Account(), cells=cells)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            assert call(url, web.API, cookie="valid")[0] == 200
            assert call(url, "/api/calibration/status", cookie="valid")[0] == 404
        finally:
            server.shutdown()
            server.server_close()
