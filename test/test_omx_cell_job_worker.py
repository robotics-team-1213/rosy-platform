"""The Fleet cell-task worker's own machine principal: a free pick with the stop proof, nothing else (cell_job_worker)."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402
import cell_job_client as client_mod  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_job_worker as worker  # noqa: E402

WORKER = guards.Principal(guards.ROLE_MACHINE, worker.WORKER_ID)
MACHINE = guards.Principal(guards.ROLE_MACHINE, guards.ROLE_MACHINE)
PICK = {"arm": "arm_s", "config": "cell-s.json", "catalog": "catalog-live.json", "roi": [0, 0, 10, 10], "source": "free:belt",
        "dest": "outbound", "at_px": "320,240", "map_only": True}
FOLDED = {"folded": True, "chunk": None, "fault": None, "human_hold_latched": False}
ONLINE = {"online": True, "blocked": False, "reason": None}


def _runner(tmp_path, monkeypatch, live=FOLDED):
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "chunks-s.json", "catalog-live.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    (tmp_path / "chunk-io-s").mkdir()
    (tmp_path / "chunk-io-s" / "live.json").write_text(json.dumps({**live, "t": time.time()}), encoding="utf-8")
    popen = Mock(return_value=Mock(poll=Mock(return_value=0)))
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    runner = api.Runner(tmp_path, lease_dir=tmp_path / "leases", motor_health_dir=tmp_path / "health",
                        incident_check_fn=lambda _arm: None, fleet_safety_check_fn=lambda _arm: ONLINE)
    return runner, popen


def test_the_worker_token_resolves_only_to_the_worker_principal():
    assert worker.authenticate_worker("Bearer " + "w" * 32, "w" * 32) == WORKER
    assert worker.authenticate_worker("Bearer " + "x" * 32, "w" * 32) is None
    assert worker.authenticate_worker("Bearer " + "w" * 32, None) is None  # feature off: nothing matches


def test_the_worker_token_file_is_optional_and_never_equals_another_token(tmp_path, monkeypatch):
    monkeypatch.delenv(worker.TOKEN_ENV, raising=False)
    assert worker.read_worker_token("h" * 32) is None
    monkeypatch.setenv(worker.TOKEN_ENV, str(tmp_path / "absent.token"))
    assert worker.read_worker_token("h" * 32) is None
    tok = tmp_path / "w.token"
    tok.write_text("w" * 32, encoding="utf-8")
    os.chmod(tok, 0o600)
    monkeypatch.setenv(worker.TOKEN_ENV, str(tok))
    assert worker.read_worker_token("h" * 32, None, "m" * 32) == "w" * 32
    assert worker.read_worker_token("h" * 32, "w" * 32) is None  # equal to another token: off, not SystemExit


@pytest.mark.parametrize("change", [
    {"source": "belt"}, {"source": "inbound"}, {"map_only": False}, {"at_px": ""}, {"reviewed_auto": True},
])
def test_the_worker_may_only_start_a_free_map_only_pick_at_a_pixel_never_reviewed_auto(change):
    params = {**PICK, **change}
    eff, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], params, WORKER, moves_arm_fn=api.moves_arm)
    assert err and err["code"] == 403 and err["error_code"] == "WORKER_SCOPE_FORBIDDEN"


@pytest.mark.parametrize("extra", [
    {"verify_zones": False}, {"operator": "alice"}, {"proposer": "alice"}, {"layers_below": 1}, {"neighbour_clear_mm": 12.0},
    {"reviewed_auto": False}, {"reviewed_auto": True}, {"mystery": 1},
])
def test_the_worker_scope_is_a_strict_allowlist_of_the_keys_it_sends(extra):
    _, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], {**PICK, **extra}, WORKER, moves_arm_fn=api.moves_arm)
    assert err and err["code"] == 403 and err["error_code"] == "WORKER_SCOPE_FORBIDDEN"


def test_every_key_the_worker_sends_is_allowed_and_verify_zones_only_as_true():
    import cell_task_motion as ctm

    _, params = ctm.free_pick_request({"at_px": [320, 240], "object": "box", "colour": "red"}, arm_id="arm_a", config="cell-s.json",
                                      catalog="catalog-live.json", roi=(0, 0, 10, 10), src="belt", dst="outbound")
    assert params["verify_zones"] is True and set(params) <= worker.ALLOWED_KEYS
    _, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], params, WORKER, moves_arm_fn=api.moves_arm)
    assert err is None


@pytest.mark.parametrize("content,others", [("", ()), ("short", ()), ("w" * 32, ("w" * 32,))])
def test_a_bad_worker_token_file_turns_the_feature_off_instead_of_stopping_the_api(tmp_path, monkeypatch, capsys, content, others):
    tok = tmp_path / "w.token"
    tok.write_text(content, encoding="utf-8")
    os.chmod(tok, 0o600)
    monkeypatch.setenv(worker.TOKEN_ENV, str(tok))
    assert worker.read_worker_token("h" * 32, *others) is None
    assert capsys.readouterr().err.count("principal off") == 1


@pytest.mark.parametrize("drop", ["map_only", "at_px"])
def test_a_missing_map_only_or_pixel_is_refused(drop):
    params = {k: v for k, v in PICK.items() if k != drop}
    _, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], params, WORKER, moves_arm_fn=api.moves_arm)
    assert err["error_code"] == "WORKER_SCOPE_FORBIDDEN"


def test_the_worker_is_refused_every_other_job_and_the_plain_machine_principal_still_cannot_pick():
    _, err = guards.authorize_principal("remap", api.JOBS["remap"], {"arm": "arm_s", "config": "cell-s.json"}, WORKER, moves_arm_fn=api.moves_arm)
    assert err["error_code"] == "WORKER_SCOPE_FORBIDDEN"
    eff, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], PICK, WORKER, moves_arm_fn=api.moves_arm)
    assert err is None and "operator" not in eff and "reviewed_auto" not in eff
    _, err = guards.authorize_principal("auto_pick", api.JOBS["auto_pick"], PICK, MACHINE, moves_arm_fn=api.moves_arm)
    assert err["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"  # the shared machine token gained nothing


def test_the_proof_is_still_required_and_commissioning_is_added_only_after_it(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live={**FOLDED, "folded": False})
    res = runner.start("auto_pick", PICK, principal=WORKER)
    assert res["code"] == 409 and res["error_code"] == "STOP_PROOF_NOT_FOLDED" and res["stop_proof"]["ok"] is False
    popen.assert_not_called()


def test_a_passing_proof_starts_the_pick_with_the_same_tail_as_the_human_path(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch)
    res = runner.start("auto_pick", PICK, principal=WORKER)
    assert res["code"] == 202 and runner.runs[res["id"]]["stop_proof"]["ok"] is True
    argv = popen.call_args.args[0]
    assert argv[-2:] == ["--commissioning", "--person-at-switch"] and "--from" in argv and argv[argv.index("--from") + 1] == "free:belt"
    assert runner.runs[res["id"]]["principal_id"] == worker.WORKER_ID


def test_reviewed_auto_from_the_worker_is_refused_before_any_process(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch)  # reviewed_auto would skip the proof and the commissioning tail
    res = runner.start("auto_pick", {**PICK, "reviewed_auto": True}, principal=WORKER)
    assert res["code"] == 403 and res["error_code"] == "WORKER_SCOPE_FORBIDDEN"
    popen.assert_not_called()


def test_over_http_the_worker_token_reaches_only_its_scope(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch)
    srv = api.make_server("127.0.0.1", 0, "h" * 32, runner, machine_token="m" * 32, worker_token="w" * 32)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}"
        w = client_mod.CellJobClient(url, "w" * 32)
        with pytest.raises(client_mod.CellJobError) as other:
            w.start("remap", {"arm": "arm_s", "config": "cell-s.json"})
        assert other.value.status_code == 403
        with pytest.raises(client_mod.CellJobError) as bad:
            client_mod.CellJobClient(url, "x" * 32).start("auto_pick", PICK)
        assert bad.value.status_code == 401
        with pytest.raises(client_mod.CellJobError) as reviewed:
            w.start("auto_pick", {**PICK, "reviewed_auto": True})
        assert reviewed.value.status_code == 403
        assert "id" in w.start("auto_pick", PICK, idempotency_key="fleet-t-1-lease")
    finally:
        srv.shutdown()
