"""PR-2 regression tests: D-430 safety tags, :8781 token split/gates, worker 3-state, upkeep, depth lock, zone verification."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_auto_setup as setup  # noqa: E402
import cell_depth_lock as cdl  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_client as client_mod  # noqa: E402
import cell_task_worker as ctw  # noqa: E402
import cell_upkeep_checks as cuk  # noqa: E402
import cell_zone_verification as czv  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "catalog-live.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


def test_job_log_tail_is_bounded_when_a_writer_appends():
    class GrowingLog(io.BytesIO):
        def seek(self, offset, whence=os.SEEK_SET):
            position = super().seek(offset, whence)
            if whence == os.SEEK_END:
                self.write(b"more")
                super().seek(position)
            return position

    class LogPath:
        def open(self, mode):
            assert mode == "rb"
            return GrowingLog(b"old-tail")

    assert api.read_tail_bytes(LogPath(), 4) == b"tail"
    assert api.read_tail_bytes(LogPath(), 0) == b""


def test_platform_parts_registers_d1072_safety_review_paths():
    manifest = yaml.safe_load((ROOT / "tools/harness/platform_parts.yaml").read_text(encoding="utf-8"))
    review = set(manifest["safety_review_paths"])
    expected = {
        "deploy/robot/omx/cell_job_api.py",
        "deploy/robot/omx/cell_job_spec.py",
        "deploy/robot/omx/cell_job_validators.py",
        "deploy/robot/omx/cell_job_guards.py",
        "deploy/robot/omx/cell_depth_lock.py",
        "deploy/robot/omx/cell_recovery.py",
        "deploy/robot/omx/cell_task_transport.py",
        "deploy/robot/omx/cell_vlm_orchestrator.py",
        "deploy/robot/omx/cell_envelope_review.py",
        "operations/fleet/fleet/server/sitemap/pipeline_cell_task_routes.py",
        "operations/fleet/fleet/server/sitemap/pipeline_camera_routes.py",
        "operations/fleet/fleet/server/sitemap/pipeline_evidence.py",
    }
    assert expected <= review


def test_dual_token_auth_machine_commissioning_ban_and_proposer_binding(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    procs = []
    monkeypatch.setattr(
        api.subprocess, "Popen",
        lambda argv, **kw: procs.append(Mock(argv=argv, env=kw.get("env"), poll=Mock(return_value=0))) or procs[-1],
    )
    runner = api.Runner(wd, lock_dir=wd)
    human_tok, machine_tok = "h" * 32, "m" * 32
    with pytest.raises(ValueError, match="must differ"):
        api.make_server("127.0.0.1", 0, human_tok, runner, machine_token=human_tok)

    srv = api.make_server("127.0.0.1", 0, human_tok, runner, machine_token=machine_tok)
    assert srv.RequestHandlerClass.timeout == 10
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mclient = client_mod.CellJobClient(f"http://127.0.0.1:{srv.server_port}", machine_tok)
        hclient = client_mod.CellJobClient(f"http://127.0.0.1:{srv.server_port}", human_tok)

        with pytest.raises(client_mod.CellJobError) as e_comm:
            mclient.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
        assert e_comm.value.status_code == 403

        with pytest.raises(client_mod.CellJobError) as e_unrev:
            mclient.start("auto_pick", {
                "arm": "arm_a", "config": "cell-a.json", "catalog": "catalog-live.json",
                "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
            })
        assert e_unrev.value.status_code == 403

        with pytest.raises(client_mod.CellJobError) as e_spoof:
            mclient.start("auto_pick", {
                "arm": "arm_a", "config": "cell-a.json", "catalog": "catalog-live.json",
                "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
                "reviewed_auto": True, "operator": "op_k", "proposer": "spoofed",
            })
        assert e_spoof.value.status_code == 403

        with pytest.raises(client_mod.CellJobError) as e_self:
            mclient.start("auto_pick", {
                "arm": "arm_a", "config": "cell-a.json", "catalog": "catalog-live.json",
                "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
                "reviewed_auto": True, "operator": "cell-job-machine",
            })
        assert e_self.value.status_code == 400

        dry = mclient.start("auto_pick_dry_run", {
            "config": "cell-a.json", "catalog": "catalog-live.json", "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
        })
        assert "id" in dry

        rev = mclient.start("auto_pick", {
            "arm": "arm_a", "config": "cell-a.json", "catalog": "catalog-live.json",
            "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
            "reviewed_auto": True, "operator": "human_lead",
        }, idempotency_key="idem-rev-1")
        replay = mclient.start("auto_pick", {
            "arm": "arm_a", "config": "cell-a.json", "catalog": "catalog-live.json",
            "roi": [0, 0, 10, 10], "source": "belt", "dest": "outbound",
            "reviewed_auto": True, "operator": "human_lead",
        }, idempotency_key="idem-rev-1")
        assert replay["id"] == rev["id"] and replay["idempotent_replay"] is True

        with pytest.raises(client_mod.CellJobError) as e_conf:
            mclient.start("calibrate_check", {"config": "cell-a.json"}, idempotency_key="idem-rev-1")
        assert e_conf.value.status_code == 409

        hum = hclient.start("remap", {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True})
        assert "id" in hum
        runner.get(rev["id"])
        runner.get(hum["id"])
        rows = [json.loads(line) for line in (wd / "cell-job-api" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        by_id = {r["id"]: r for r in rows}
        assert by_id[rev["id"]]["principal_role"] == "cell-job-machine" and by_id[rev["id"]]["proposer"] == "cell-job-machine"
        assert by_id[hum["id"]]["principal_role"] == "cell-job-human"
        assert (wd / "cell-state-dirty-arm_a.json").is_file()
        assert "--verify-zones" in procs[1].argv
    finally:
        srv.shutdown()
        srv.server_close()


def test_runner_safety_gates_incident_peer_fold_fleet_and_act_backend(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    (wd / "chunk-io-a").mkdir()
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    seen_env = []
    monkeypatch.setattr(
        api.subprocess, "Popen",
        lambda argv, **kw: seen_env.append((argv, kw.get("env") or {})) or Mock(poll=Mock(return_value=None)),
    )

    runner_inc = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda arm: f"{arm} local hold", fleet_safety_check_fn=lambda _: {"online": False, "blocked": False})
    res_inc = runner_inc.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res_inc["code"] == 409 and res_inc["error_code"] == "ARM_INCIDENT_HELD"

    res_fleet = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _: None, fleet_safety_check_fn=lambda _: {"online": True, "blocked": True, "reason": "estop"}).start(
        "remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True},
    )
    assert res_fleet["code"] == 409 and res_fleet["error_code"] == "FLEET_SAFETY_STOP"

    # Real chunk_runner_loop live.json schema (state array, no 'folded' key): extended [10, 10] blocks, folded [-60, 50] passes.
    (wd / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": None, "state": [0.0, 10.0, 10.0, 0.0, 0.0, 0.0], "t": time.time()}), encoding="utf-8")
    res_peer = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _: None, fleet_safety_check_fn=lambda _: {"online": False, "blocked": False}).start(
        "remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True},
    )
    assert res_peer["code"] == 409 and res_peer["error_code"] == "PEER_ARM_NOT_FOLDED"

    # Peer incident hold also blocks arm_b.
    res_peer_inc = api.Runner(
        wd, lock_dir=wd,
        incident_check_fn=lambda arm: "peer held" if arm == "arm_a" else None,
        fleet_safety_check_fn=lambda _: {"online": False, "blocked": False},
    ).start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert res_peer_inc["code"] == 409 and res_peer_inc["error_code"] == "PEER_ARM_NOT_FOLDED"

    (wd / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": None, "state": [0.0, -60.0, 50.0, 0.0, 0.0, 0.0], "t": time.time()}), encoding="utf-8")
    r_ok = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _: None, fleet_safety_check_fn=lambda _: {"online": False, "blocked": False})

    # Regression #1: moving goal_slot=9 (tray) on cell_policy_drive is blocked with 400; dry_run=True allowed.
    bad_tray = r_ok.start("cell_policy_drive", {
        "arm": "arm_b", "config": "cell-b.json", "library": "chunks-s.json",
        "policy_root": "~/m", "policy_revision": "a" * 64, "cell_calibration": "cal.json",
        "max_chunks": 2, "operator": "human_op", "goal_slot": 9, "person_at_switch": True,
    })
    assert bad_tray["code"] == 400 and "AMR bed" in bad_tray["error"]
    dry_tray = r_ok.start("cell_policy_drive", {
        "arm": "arm_b", "config": "cell-b.json", "library": "chunks-s.json",
        "policy_root": "~/m", "policy_revision": "a" * 64, "cell_calibration": "cal.json",
        "max_chunks": 2, "operator": "human_op", "goal_slot": 9, "dry_run": True,
    })
    assert dry_tray["code"] == 202

    # Regression #8: machine token passing bogus reviewed_auto=True on remap gets 403 MACHINE_COMMISSIONING_FORBIDDEN.
    bogus_rev = r_ok.start(
        "remap", {"arm": "arm_b", "config": "cell-b.json", "reviewed_auto": True},
        principal=api.Principal("cell-job-machine", "cell-job-machine"),
    )
    assert bogus_rev["code"] == 403 and bogus_rev["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"

    started = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _: None, fleet_safety_check_fn=lambda _: {"online": False, "blocked": False}).start("cell_policy_drive", {
        "arm": "arm_b", "config": "cell-b.json", "library": "chunks-s.json",
        "policy_root": "~/m", "policy_revision": "a" * 64, "cell_calibration": "cal.json",
        "max_chunks": 2, "operator": "human_op", "goal_slot": 3, "act_backend": "openvino", "person_at_switch": True,
    })
    assert started["code"] == 202
    assert "--goal-slot" in seen_env[-1][0] and "3" in seen_env[-1][0]
    assert "--act-backend" not in seen_env[-1][0]
    assert seen_env[-1][1]["ROSY_ACT_BACKEND"] == "openvino"


def test_peer_fold_lease_timestamp_and_fleet_online_fail_closed(tmp_path, monkeypatch):
    import cell_arm_lease
    import cell_job_guards as guards
    import ssl as _ssl

    wd = _make_workdir(tmp_path)
    (wd / "chunk-io-a").mkdir()
    leases = tmp_path / "leases"
    leases.mkdir()

    # Stale dead-pid lease does not force peer_lease=True, so absent live.json allows unlocked folded assumption.
    (leases / "arm_a.json").write_text(json.dumps({"pid": 999999999, "hold": False, "expires": time.time() + 60}), encoding="utf-8")
    assert guards.check_peer_ab_folded(
        "arm_b", wd, leases, wd,
        session_lock_held_fn=lambda *_: False, read_json_fn=guards.read_json_dict,
        live_max_age_s=5.0, incident_check_fn=lambda _: None,
    ) is None

    # Active lease with missing or NaN timestamp in live.json fails closed.
    cell_arm_lease.claim("arm_a", "cell-job-api:1", "task", pid=os.getpid(), root=leases)
    (wd / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": None, "state": [0.0, -60.0, 50.0, 0.0, 0.0, 0.0]}), encoding="utf-8")
    assert "timestamp" in (guards.check_peer_ab_folded(
        "arm_b", wd, leases, wd,
        session_lock_held_fn=lambda *_: False, read_json_fn=guards.read_json_dict,
        live_max_age_s=5.0, incident_check_fn=lambda _: None,
    ) or "")

    # Direct tests for check_fleet_safety_online fail-closed cases.
    tok = tmp_path / "fleet.tok"
    tok.write_text("x" * 32, encoding="utf-8")
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy", encoding="utf-8")

    # Missing ca_file fails closed.
    r_ca = guards.check_fleet_safety_online("arm_s", fleet_r_url="https://fleet.local", fleet_token_file=tok, ca_file=tmp_path / "missing.pem")
    assert r_ca["online"] and r_ca["blocked"]

    monkeypatch.setattr(guards.ssl, "create_default_context", lambda **_k: None)

    def _raise_http(*_a, **_k):
        raise urllib.error.HTTPError("https://fleet.local", 403, "Forbidden", {}, None)

    monkeypatch.setattr(guards, "urlopen", _raise_http)
    assert guards.check_fleet_safety_online("arm_s", fleet_r_url="https://fleet.local", fleet_token_file=tok, ca_file=ca)["blocked"] is True

    def _raise_ssl(*_a, **_k):
        raise _ssl.SSLError("cert verify failed")

    monkeypatch.setattr(guards, "urlopen", _raise_ssl)
    assert guards.check_fleet_safety_online("arm_s", fleet_r_url="https://fleet.local", fleet_token_file=tok, ca_file=ca)["blocked"] is True

    class _Resp:
        def __init__(self, payload):
            self._p = json.dumps(payload).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def read(self, *_a): return self._p

    for bad_payload in (
        {"human_safety": {"active_estop": False}, "cells": {}},  # missing human_detected
        {"human_safety": {"active_estop": False, "human_detected": {}}, "cells": []},  # non-dict cells
        {"human_safety": {"active_estop": False, "human_detected": {}}, "cells": {"cell_s": {"phase": "HUMAN_HOLD"}}},
        {"human_safety": {"active_estop": False, "human_detected": {}}, "cells": {"cell_s": {"phase": "IDLE", "prev_phase": "ABORTED"}}},
    ):
        monkeypatch.setattr(guards, "urlopen", lambda *_a, _pl=bad_payload, **_k: _Resp(_pl))
        assert guards.check_fleet_safety_online("arm_s", fleet_r_url="https://fleet.local", fleet_token_file=tok, ca_file=ca)["blocked"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl.flock required")
def test_depth_d435_lock_blocks_camera_job_and_zone_depth(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    monkeypatch.setenv("ROSY_OMX_HOME", str(wd))
    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(czv, "DEPTH_WAIT_S", 0.05)

    with cdl.hold_depth_lock(timeout_s=1.0, lock_dir=wd):
        assert cdl.is_depth_lock_held(wd) is True
        res = api.Runner(wd, lock_dir=wd).start("calibrate_check", {"config": "cell-s.json"})
        assert res["code"] == 409 and res["error_code"] == "DEPTH_LOCK_HELD"
        depth, receipt, why = czv._depth_after({}, time.time())
        assert depth is None and receipt is None and why == "depth-d435.lock busy"
    assert cdl.is_depth_lock_held(wd) is False


def test_worker_three_state_safety_hold_scope(tmp_path, monkeypatch):
    prep = tmp_path / "prep"
    leases = tmp_path / "leases"
    monkeypatch.setenv("ROSY_ARM_LEASES", str(leases))
    for sfx in ("s", "a", "b"):
        d = prep / f"chunk-io-{sfx}"
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    import cell_arm_lease

    cell_arm_lease.claim("arm_s", "cell-task-worker:1", "task", pid=os.getpid(), root=leases)
    cell_arm_lease.claim("arm_a", "cell-job-api:2", "manual", pid=os.getpid(), root=leases)
    (prep / "chunk-io-b" / "live.json").write_text(json.dumps({"chunk": "grasp_pick"}), encoding="utf-8")
    monkeypatch.setattr(ctw, "_SAFETY_LISTING_RETRY_S", 0, raising=False)
    monkeypatch.setattr(ctw, "_poll_status_ack", lambda *_a: ({"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}, 0))

    assert ctw.poll_and_execute_once(None, request_fn=lambda *_: None, live_act_fn=pytest.fail, prep_dir=prep) == []
    assert (prep / "chunk-io-s" / "chunk-cmd").read_bytes() == b"human-hold\n"
    assert (prep / "chunk-io-b" / "chunk-cmd").read_bytes() == b"human-hold\n"
    assert (prep / "chunk-io-a" / "chunk-cmd").read_bytes() == b""

    for sfx in ("s", "a", "b"):
        (prep / f"chunk-io-{sfx}" / "chunk-cmd").write_bytes(b"")
    assert ctw.poll_and_execute_once(
        None,
        request_fn=lambda *_: {"tasks": [], "human_safety": {"active_estop": True, "human_detected": {}}},
        live_act_fn=pytest.fail,
        prep_dir=prep,
    ) == []
    for sfx in ("s", "a", "b"):
        assert (prep / f"chunk-io-{sfx}" / "chunk-cmd").read_bytes() == b"human-hold\n"


def test_upkeep_autonomous_mode_and_direct_verify_zones(tmp_path):
    robot = tmp_path / "robot"
    robot.write_text("", encoding="utf-8")
    rec = {"robot": {"port": str(robot)}, "teleop": {"port": str(tmp_path / "missing-leader")}}
    assert cuk.check_boards(rec, mode="teleop")["status"] == "fail"
    assert cuk.check_boards(rec, mode="autonomous")["status"] == "ok"
    assert czv.zone_check_enabled({"_fleet_task": False, "_verify_zones": True}) is True
    assert czv.zone_check_enabled({"_fleet_task": False, "_verify_zones": False}) is False
    args = setup.pick_parser("doc").parse_args([
        "--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "belt", "--verify-zones",
    ])
    assert args.verify_zones is True


def test_peer_fold_passive_motor_health_recovery_and_fail_closed(tmp_path):
    import cell_arm_lease
    import cell_job_guards as guards

    wd = _make_workdir(tmp_path)
    (wd / "chunk-io-a").mkdir(exist_ok=True)
    leases = tmp_path / "leases"
    leases.mkdir()
    mh_dir = tmp_path / "motor-health"
    mh_dir.mkdir()
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    now = time.time()

    def _cal_doc(*, lift_max=4095, drive_mode=0, homing_offset=0):
        joints = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
        return {
            j: {"id": 11 + i, "drive_mode": drive_mode if j == "shoulder_lift" else 0,
                "homing_offset": homing_offset if j == "shoulder_lift" else 0,
                "range_min": 0, "range_max": lift_max if j == "shoulder_lift" else 4095}
            for i, j in enumerate(joints)
        }

    def _mh_doc(*, obs_at=now, status="active", torque=False, fault=False, raw2=854, raw3=3170, hw_err=0):
        raws = [2063, raw2, raw3, 3056, 2973, 2017]
        return {
            "schema_version": "rosy.motor-health.v1", "owner_id": "arm_a", "status": status,
            "observed_at": obs_at, "stop_reasons": [],
            "motors": [{"id": 11 + i, "present_raw": float(raws[i]), "torque_enabled": torque,
                        "fault": fault, "hardware_error": hw_err} for i in range(6)],
        }

    def _check():
        return guards.check_peer_ab_folded(
            "arm_b", wd, leases, wd, session_lock_held_fn=lambda *_: False, read_json_fn=guards.read_json_dict,
            live_max_age_s=15.0, incident_check_fn=lambda _: None, motor_health_dir=mh_dir, calibration_dir=cal_dir,
        )

    # Stale live.json with stuck chunk recovers ONLY when unlocked/unleased, cal matches, and passive motor-health is fresh, torque-off, folded.
    (wd / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": "goto above_pick", "t": now - 3600.0}), encoding="utf-8")
    (mh_dir / "arm_a.json").write_text(json.dumps(_mh_doc()), encoding="utf-8")
    (cal_dir / "arm_a_follower.json").write_text(json.dumps(_cal_doc()), encoding="utf-8")
    assert _check() is None

    # Narrow/bad follower calibration or missing cal fails closed even with low raw ticks.
    for bad_cal in (None, _cal_doc(lift_max=3000), _cal_doc(drive_mode=1), _cal_doc(homing_offset=50)):
        cpath = cal_dir / "arm_a_follower.json"
        cpath.unlink(missing_ok=True) if bad_cal is None else cpath.write_text(json.dumps(bad_cal), encoding="utf-8")
        assert _check() is not None
    (cal_dir / "arm_a_follower.json").write_text(json.dumps(_cal_doc()), encoding="utf-8")

    # Every unsafe passive motor-health state or live/latched condition remains strictly fail-closed.
    for bad_mh in (
        None, _mh_doc(obs_at=now - 60.0), _mh_doc(status="ended"), _mh_doc(torque=True),
        _mh_doc(fault=True), _mh_doc(hw_err=False), _mh_doc(raw2=2048, raw3=2048),
    ):
        mh_path = mh_dir / "arm_a.json"
        mh_path.unlink(missing_ok=True) if bad_mh is None else mh_path.write_text(json.dumps(bad_mh), encoding="utf-8")
        assert _check() is not None

    (mh_dir / "arm_a.json").write_text(json.dumps(_mh_doc()), encoding="utf-8")
    for live_payload in (
        {"chunk": "goto above_pick", "t": now},
        {"chunk": None, "human_hold_latched": True, "t": now - 3600.0},
        {"chunk": "goto above_pick"},
        {"chunk": "goto above_pick", "t": now + 100.0},
        {"chunk": "goto above_pick", "t": 10**400},
    ):
        (wd / "chunk-io-a" / "live.json").write_text(json.dumps(live_payload), encoding="utf-8")
        assert _check() is not None

    (wd / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": "goto above_pick", "t": now - 3600.0}), encoding="utf-8")
    cell_arm_lease.claim("arm_a", "cell-job-api:1", "task", pid=os.getpid(), root=leases)
    assert _check() is not None
