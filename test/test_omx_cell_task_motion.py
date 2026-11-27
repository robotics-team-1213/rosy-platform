"""Fleet cell-task motions on the arm cell: the free pick goes through the cell job API as the machine principal."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_task_exec as cte  # noqa: E402
import cell_task_motion as ctm  # noqa: E402
from cell_job_client import CellJobError  # noqa: E402

SHA = "ab" * 32
FREE = {"kind": "free_pick", "anchor_site": "belt", "at_px": [320, 240], "dst_site": "pallet", "frame_seq": 41,
        "frame_sha256": SHA, "object": "box", "colour": "red"}
PUSH = {"kind": "push", "site": "belt", "px": [300, 200], "dir": [1, 0], "mm": 10, "frame_seq": 41, "frame_sha256": SHA}
HANDOFF = {"task_id": "t-1", "cell_id": "cell_ab", "arm_id": "arm_s", "tier": 1, "handoff_lease_id": "lease-1",
           "src_site": "belt", "dst_site": "pallet", "motion": FREE}
HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]
ZONE = {"verified": True, "basis": "predefined_side_and_top_target_zones", "z_gate": {"verdict": "PASS"},
        "target": {"site": "pallet", "area": "pallet", "tier": 1}}
PARK = {"command": "park", "ok": True, "settled": True, "fault": None, "state": [0.5, -57.0, 49.0, 51.0, -4.0, 58.0], "t": 12.5}
PLACED = {"result": "placed", "attempts": [{"verify": {"found": True, "inside": True, "verified": True, "basis": "map"},
                                            "transfer": {"result": "placed", "steps": [PARK]}, "zone_verification": ZONE}]}


class FakeClient:
    def __init__(self, result=None, exit_code=0, start_error=None):
        self.calls, self.result, self.exit_code, self.start_error = [], result or PLACED, exit_code, start_error

    def start(self, job, params, *, idempotency_key=None):
        self.calls.append((job, params, idempotency_key))
        if self.start_error:
            raise self.start_error
        return {"id": "job-1"}

    def wait(self, job_id, *, timeout_s):
        return {"id": job_id, "running": False, "exit": self.exit_code, "structured_result": self.result}


def test_free_pick_maps_to_auto_pick_from_the_anchor_on_the_map_alone():
    job, params = ctm.free_pick_request(FREE, arm_id="arm_b", config="cell-arm-b-stack.json", catalog="object-catalog-orange.json",
                                        roi=(10, 340, 230, 478), src="belt", dst="pallet-l0")
    assert job == "auto_pick"
    assert params == {"arm": "arm_b", "config": "cell-arm-b-stack.json", "catalog": "object-catalog-orange.json",
                      "roi": [10, 340, 230, 478], "source": "free:belt", "dest": "pallet-l0", "at_px": "320,240",
                      "map_only": True, "verify_zones": True, "object": "box", "colour": "red"}  # verify_zones: the API path has no --task-id
    assert not {"operator", "proposer", "reviewed_auto", "person_at_switch"} & set(params)  # never from the model or the worker


def test_push_maps_to_the_cell_push_job_in_millimetres_of_pixels_and_direction():
    job, params = ctm.push_request(PUSH, arm_id="arm_a", config="cell-arm-a-stack.json", catalog="object-catalog-orange.json", roi=(1, 2, 3, 4))
    assert job == "push" and params == {"arm": "arm_a", "config": "cell-arm-a-stack.json", "site": "belt", "roi": [1, 2, 3, 4],
                                        "catalog": "object-catalog-orange.json", "px_x": 300, "px_y": 200, "dir_x": 1, "dir_y": 0, "mm": 10}
    assert not {"operator", "proposer", "reviewed_auto", "person_at_switch"} & set(params)


def test_idempotency_key_is_deterministic_per_task_so_a_reclaim_replays_and_never_moves_twice():
    key = ctm.idempotency_key(HANDOFF)
    assert re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) and "t-1" in key and "lease-1" in key
    assert ctm.idempotency_key(dict(HANDOFF)) == key  # same task + lease: same key, the cell replays the earlier job
    assert len(ctm.idempotency_key({**HANDOFF, "task_id": "x" * 300})) == 128


def test_run_job_starts_with_the_key_and_returns_the_structured_result():
    client = FakeClient()
    proc, refusal = ctm.run_job(HANDOFF, "auto_pick", {"arm": "arm_b"}, client=client)
    assert refusal is None and proc.returncode == 0 and json.loads(proc.stdout) == PLACED
    assert client.calls == [("auto_pick", {"arm": "arm_b"}, ctm.idempotency_key(HANDOFF))]


@pytest.mark.parametrize("error,prefix", [
    (CellJobError(403, "cell-job-machine cannot start unreviewed moving job auto_pick"), "CELL_JOB_REFUSED:403:"),
    (CellJobError(409, "Fleet safety stop"), "CELL_JOB_REFUSED:409:"), (OSError("down"), "CELL_JOB_UNREACHABLE::"),
])
def test_a_refusal_or_unreachable_cell_is_reported_never_retried_around(error, prefix):
    client = FakeClient(start_error=error)
    proc, refusal = ctm.run_job(HANDOFF, "auto_pick", {}, client=client)
    assert proc is None and refusal.startswith(prefix) and len(client.calls) == 1


def test_without_the_worker_token_nothing_is_sent_and_no_other_token_is_read(monkeypatch, tmp_path):
    monkeypatch.delenv(ctm.TOKEN_ENV, raising=False)
    monkeypatch.setenv("ROSY_CELL_JOB_TOKEN", "h" * 32)
    monkeypatch.setenv("ROSY_CELL_JOB_MACHINE_TOKEN_FILE", str(tmp_path / "machine.token"))
    monkeypatch.setattr(ctm, "CellJobClient", lambda *a, **k: pytest.fail("a client was built without a worker token"))
    assert ctm.run_job(HANDOFF, "auto_pick", {}) == (None, "CELL_JOB_WORKER_TOKEN_MISSING")
    monkeypatch.setenv(ctm.TOKEN_ENV, str(tmp_path / "absent.token"))
    assert ctm.run_job(HANDOFF, "auto_pick", {}) == (None, "CELL_JOB_WORKER_TOKEN_MISSING")


def test_the_worker_token_file_and_loopback_win_over_the_token_and_url_env(monkeypatch, tmp_path):
    seen = {}

    class Req:  # stands in for urllib's response and records what was sent
        headers = {}
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.body

    def fake_urlopen(req, timeout=None):
        seen.setdefault("calls", []).append((req.full_url, req.get_header("Authorization")))
        return Req(b'{"id": "job-1", "running": false, "exit": 0, "structured_result": {}}')

    tok = tmp_path / "worker.token"
    tok.write_text("w" * 32 + "\n", encoding="utf-8")
    monkeypatch.setenv(ctm.TOKEN_ENV, str(tok))
    monkeypatch.setenv("ROSY_CELL_JOB_TOKEN", "h" * 32)  # the human token the client would otherwise prefer
    monkeypatch.setenv("ROSY_CELL_JOB_URL", "http://203.0.113.9:8781")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    proc, refusal = ctm.run_job(HANDOFF, "auto_pick", {"arm": "arm_b"})
    assert refusal is None and proc.returncode == 0
    assert seen["calls"] and all(url.startswith("http://127.0.0.1:8781/") and auth == "Bearer " + "w" * 32 for url, auth in seen["calls"])


@pytest.mark.parametrize("env_url,expected", [("http://203.0.113.20:8781", "http://203.0.113.20:8781"), ("  ", ctm.LOOPBACK_URL), (None, ctm.LOOPBACK_URL)])
def test_the_worker_url_comes_only_from_the_worker_env_var_and_defaults_to_loopback(monkeypatch, tmp_path, env_url, expected):
    tok = tmp_path / "worker.token"
    tok.write_text("w" * 32, encoding="utf-8")
    monkeypatch.setenv(ctm.TOKEN_ENV, str(tok))
    monkeypatch.setenv("ROSY_CELL_JOB_URL", "http://203.0.113.9:8781")  # the shared one is ignored
    monkeypatch.setenv("ROSY_CELL_JOB_TOKEN", "h" * 32)
    monkeypatch.delenv(ctm.URL_ENV, raising=False) if env_url is None else monkeypatch.setenv(ctm.URL_ENV, env_url)
    built = []

    def fake_client(url, token):
        built.append((url, token))
        return FakeClient()

    monkeypatch.setattr(ctm, "CellJobClient", fake_client)
    assert ctm.run_job(HANDOFF, "auto_pick", {})[1] is None
    assert built == [(expected, "w" * 32)]


def _exec(tmp_path, monkeypatch, handoff, client_result=None, **fake):
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": HOME}), encoding="utf-8")
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({"plan_path": str(tmp_path / "grasp-plan.json")}), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda arm, prep, now=None: {"folded": True, "state": None, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0, "site": "belt"})
    monkeypatch.setattr(cte, "zone_acceptance", lambda zone, handoff, dst: True)  # slot matching is unchanged and covered in test_omx_cell_task_exec_measured
    client = FakeClient(client_result, **fake)
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: pytest.fail("a free pick must not start its own cell_auto_pick"))
    monkeypatch.setattr(cte, "run_job", lambda h, job, params: ctm.run_job(h, job, params, client=client))
    return cte.execute_guarded_cell_task(handoff, prep_dir=tmp_path), client


def test_the_worker_runs_the_free_pick_through_the_job_api_and_measures_the_result_as_before(tmp_path, monkeypatch):
    out, client = _exec(tmp_path, monkeypatch, HANDOFF)
    (job, params, key), = client.calls
    assert job == "auto_pick" and params["source"] == "free:belt" and params["at_px"] == "320,240" and params["map_only"] is True
    assert key == ctm.idempotency_key(HANDOFF)
    assert out["stage_result"]["task_verified"] is True and out["stop_event"]["folded"] is True and "error" not in out
    assert out["stage_result"]["raw"] == PLACED and out["stage_result"]["verification"]["basis"] == ZONE["basis"]  # the cell's own measured record


def test_a_cell_refusal_aborts_with_its_code_and_a_not_folded_stop_event(tmp_path, monkeypatch):
    err = CellJobError(403, "MACHINE_COMMISSIONING_FORBIDDEN")
    out, _ = _exec(tmp_path, monkeypatch, HANDOFF, start_error=err)
    assert out["error"].startswith("CELL_JOB_REFUSED:403:") and out["stage_result"]["task_verified"] is False
    assert out["stop_event"] == {"command": "stop", "ok": False, "folded": False}


def test_a_failed_pick_is_not_a_verified_task(tmp_path, monkeypatch):
    out, _ = _exec(tmp_path, monkeypatch, HANDOFF, client_result={"result": "no object within 25 px of [320, 240]"}, exit_code=1)
    assert out["stage_result"]["task_verified"] is False and out["error"].startswith("no object")


@pytest.mark.parametrize("handoff", [
    {**HANDOFF, "motion": PUSH}, {**HANDOFF, "motion": {"kind": "area_xyz"}}, {**HANDOFF, "motion": "free_pick"},
    {**HANDOFF, "cell_id": "cell_s"},
])
def test_a_push_or_unknown_motion_never_reaches_the_cell(tmp_path, monkeypatch, handoff):
    out, client = _exec(tmp_path, monkeypatch, handoff)
    assert out["error"] == "CELL_MOTION_NOT_EXECUTABLE" and client.calls == []
    assert out["stop_event"] == {"command": "stop", "ok": False, "folded": False}
