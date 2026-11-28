"""Cooperative cancel of a running cell job (D-1081): marker honoured by Guarded.act, API route, client, worker."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_safety as cas  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_cancel as cancel_mod  # noqa: E402
import cell_job_client as client_mod  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_job_worker as worker  # noqa: E402
import cell_task_motion as ctm  # noqa: E402

WORKER = guards.Principal(guards.ROLE_MACHINE, worker.WORKER_ID)
MACHINE = guards.Principal(guards.ROLE_MACHINE, guards.ROLE_MACHINE)
HUMAN = guards.Principal(guards.ROLE_HUMAN, guards.ROLE_HUMAN)
PICK = {"arm": "arm_s", "config": "cell-s.json", "catalog": "catalog-live.json", "roi": [0, 0, 10, 10], "source": "free:belt",
        "dest": "outbound", "at_px": "320,240", "map_only": True}
DRY = {"config": "cell-s.json", "source": "inbound", "catalog": "catalog-live.json", "roi": [0, 0, 10, 10], "dest": "outbound"}
ONLINE = {"online": True, "blocked": False, "reason": None}
FOLDED = {"folded": True, "chunk": None, "fault": None, "human_hold_latched": False}


def _runner(tmp_path, monkeypatch, exit_code=None):
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "chunks-s.json", "catalog-live.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    (tmp_path / "chunk-io-s").mkdir()
    (tmp_path / "chunk-io-s" / "live.json").write_text(json.dumps({**FOLDED, "t": time.time()}), encoding="utf-8")
    proc = Mock(poll=Mock(return_value=exit_code))
    popen = Mock(return_value=proc)
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    monkeypatch.setattr(api, "prove_job", lambda *a, **k: ({"ok": True, "stub": True}, None))
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    runner = api.Runner(tmp_path, lease_dir=tmp_path / "leases", motor_health_dir=tmp_path / "health",
                        incident_check_fn=lambda _arm: None, fleet_safety_check_fn=lambda _arm: ONLINE)
    return runner, popen, proc


def _audit_rows(runner):
    path = runner.out / "audit.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_start_passes_the_marker_path_to_the_child_env_only_for_a_cancellable_moving_job(tmp_path, monkeypatch):
    runner, popen, _ = _runner(tmp_path, monkeypatch)
    jid = runner.start("auto_pick", dict(PICK), principal=WORKER)["id"]
    assert popen.call_args.kwargs["env"][cancel_mod.STOP_FILE_ENV] == str(runner.out / f"stop-{jid}")
    assert cancel_mod.STOP_FILE_ENV == cas.STOP_FILE_ENV
    assert not (runner.out / f"stop-{jid}").exists()  # only a cancel writes it
    (tmp_path / "x").mkdir()
    runner2, popen2, _ = _runner(tmp_path / "x", monkeypatch)
    assert runner2.start("auto_pick_dry_run", dict(DRY))["code"] == 202
    assert cancel_mod.STOP_FILE_ENV not in popen2.call_args.kwargs["env"]


def test_cancel_authorization_idempotency_audit_and_unknown(tmp_path, monkeypatch):
    runner, _, _ = _runner(tmp_path, monkeypatch)
    jid = runner.start("auto_pick", dict(PICK), principal=WORKER)["id"]
    marker = runner.out / f"stop-{jid}"
    assert cancel_mod.cancel(runner, jid, MACHINE)["code"] == 403  # the shared machine principal cannot cancel another's job
    assert not marker.exists()
    assert cancel_mod.cancel(runner, "nope", HUMAN)["code"] == 404
    first = cancel_mod.cancel(runner, jid, WORKER)  # the starter
    assert first["code"] == 200 and first["running"] is True and first["cancel_requested"] is True and marker.exists()
    assert cancel_mod.cancel(runner, jid, HUMAN)["code"] == 200  # the human, again: idempotent
    rows = [r for r in _audit_rows(runner) if r.get("event") == "cancel_requested"]
    assert len(rows) == 1 and rows[0]["id"] == jid and rows[0]["principal_id"] == worker.WORKER_ID


def test_human_started_job_cannot_be_cancelled_by_the_worker(tmp_path, monkeypatch):
    runner, _, _ = _runner(tmp_path, monkeypatch)
    jid = runner.start("auto_pick", {**PICK, "source": "inbound", "person_at_switch": True}, principal=HUMAN)["id"]
    assert cancel_mod.cancel(runner, jid, WORKER)["code"] == 403
    assert cancel_mod.cancel(runner, jid, HUMAN)["code"] == 200


def test_cancel_of_a_job_without_a_cooperative_stop_is_not_cancellable(tmp_path, monkeypatch):
    runner, _, _ = _runner(tmp_path, monkeypatch)
    jid = runner.start("auto_pick_dry_run", dict(DRY))["id"]
    res = cancel_mod.cancel(runner, jid, HUMAN)
    assert res["code"] == 409 and res["error_code"] == "JOB_NOT_CANCELLABLE"


def test_cancel_of_a_finished_job_returns_state_and_writes_nothing(tmp_path, monkeypatch):
    runner, _, _ = _runner(tmp_path, monkeypatch, exit_code=0)
    jid = runner.start("auto_pick", dict(PICK), principal=WORKER)["id"]
    res = cancel_mod.cancel(runner, jid, WORKER)
    assert res["code"] == 200 and res["running"] is False and res["cancel_requested"] is False
    assert not (runner.out / f"stop-{jid}").exists()
    assert not [r for r in _audit_rows(runner) if r.get("event") == "cancel_requested"]


def test_marker_is_removed_when_the_job_is_reaped(tmp_path, monkeypatch):
    runner, _, proc = _runner(tmp_path, monkeypatch)
    jid = runner.start("auto_pick", dict(PICK), principal=WORKER)["id"]
    cancel_mod.cancel(runner, jid, WORKER)
    marker = runner.out / f"stop-{jid}"
    assert marker.exists()
    proc.poll.return_value = 1
    runner.get(jid, 0)
    assert not marker.exists()


def test_http_cancel_route_and_client(tmp_path, monkeypatch):
    runner, _, _ = _runner(tmp_path, monkeypatch)
    server = api.make_server("127.0.0.1", 0, "h" * 40, runner, machine_token="m" * 40, worker_token="w" * 40)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        jid = runner.start("auto_pick", dict(PICK), principal=WORKER)["id"]
        with pytest.raises(client_mod.CellJobError) as exc:
            client_mod.CellJobClient(base, "m" * 40).cancel(jid)
        assert exc.value.status_code == 403
        with pytest.raises(client_mod.CellJobError) as exc:
            client_mod.CellJobClient(base, "x" * 40).cancel(jid)
        assert exc.value.status_code == 401
        with pytest.raises(client_mod.CellJobError) as exc:
            client_mod.CellJobClient(base, "h" * 40).cancel("20260101-000000-abcdef")
        assert exc.value.status_code == 404
        done = client_mod.CellJobClient(base, "w" * 40).cancel(jid, timeout=5.0)
        assert done["cancel_requested"] is True and (runner.out / f"stop-{jid}").exists()
    finally:
        server.shutdown()
        server.server_close()


class _Cell:
    def __init__(self):
        self.commands = []

    def act(self, command):
        self.commands.append(command)
        if command == "state":
            return {"command": "state", "ok": True, "state": [0.0] * 6, "t": time.time(),
                    "health": {"temp_c": [40] * 6, "pwm": [10] * 6, "current_ma": [0] * 6}}
        return {"command": command, "ok": True}


def test_guarded_honours_the_stop_marker_by_parking_and_aborting_without_a_torque_command(tmp_path, monkeypatch):
    marker = tmp_path / "stop-job"
    marker.write_text("human:human\n", encoding="utf-8")
    monkeypatch.setenv(cas.STOP_FILE_ENV, str(marker))
    cell = _Cell()
    guarded = cas.Guarded(cell, {"safety": {}})
    with pytest.raises(cas.Aborted, match="job cancel requested"):
        guarded.act("goto above_pick")
    assert cell.commands == ["park"]  # one park, nothing else: no torque command, no signal
    assert guarded.monitor.last["rule"] == "job cancel"
    assert guarded.act("park")["ok"]  # the park path itself is never blocked by the marker


def test_guarded_is_unchanged_without_the_env_var_or_with_no_marker_file(tmp_path, monkeypatch):
    monkeypatch.delenv(cas.STOP_FILE_ENV, raising=False)
    cell = _Cell()
    assert cas.Guarded(cell, {"safety": {}}).act("goto above_pick")["ok"]
    monkeypatch.setenv(cas.STOP_FILE_ENV, str(tmp_path / "never-written"))
    assert cas.Guarded(cell, {"safety": {}}).act("goto above_pick")["ok"]
    assert "park" not in cell.commands


@pytest.mark.parametrize("error", [OSError("unreadable"), ValueError("embedded null")])
def test_unreadable_marker_path_is_no_stop_request(tmp_path, monkeypatch, error):
    monkeypatch.setenv(cas.STOP_FILE_ENV, str(tmp_path / "stop-job"))

    def boom(_path):
        raise error

    monkeypatch.setattr(cas.os.path, "exists", boom)
    cell = _Cell()
    assert cas.stop_requested() is None
    assert cas.Guarded(cell, {"safety": {}}).act("goto above_pick")["ok"]


class _LostClient:
    def __init__(self, cancel_error=None):
        self.cancelled, self.cancel_error = [], cancel_error

    def start(self, job, params, *, idempotency_key=None):
        return {"id": "job-1"}

    def wait(self, job_id, *, timeout_s):
        raise TimeoutError

    def cancel(self, job_id, *, timeout=None):
        self.cancelled.append((job_id, timeout))
        if self.cancel_error:
            raise self.cancel_error
        return {}


@pytest.mark.parametrize("cancel_error", [None, OSError("down"), client_mod.CellJobError(409, "x")])
def test_worker_cancels_a_timed_out_job_once_and_still_reports_it_lost(cancel_error):
    client = _LostClient(cancel_error)
    out, err = ctm.run_job({"task_id": "t-1", "handoff_lease_id": "l-1"}, "auto_pick", {}, client=client)
    assert out is None and err.startswith("CELL_JOB_LOST:job-1:")
    assert client.cancelled == [("job-1", ctm.CANCEL_TIMEOUT_S)]


def test_worker_does_not_cancel_when_no_job_id_is_known():
    class Unreachable(_LostClient):
        def start(self, *a, **k):
            raise OSError("down")

    client = Unreachable()
    out, err = ctm.run_job({"task_id": "t-1", "handoff_lease_id": "l-1"}, "auto_pick", {}, client=client)
    assert err.startswith("CELL_JOB_UNREACHABLE") and client.cancelled == []
