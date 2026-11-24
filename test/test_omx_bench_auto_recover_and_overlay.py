"""Tests for safety-gated auto_recover (folded-only runner release) and top-camera Pick->Place goal overlay."""
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest

from test_omx_bench_record import ROOT, SimpleNamespace, bench_record, _setup


def _seed_home_library(prep, arm="arm_a", pose=None):
    letter = {"arm_a": "a", "arm_b": "b", "arm_s": "s"}[arm]
    fname = f"chunks-arm-{letter}-inplace-live.json" if arm == "arm_s" else f"chunks-topdown-guard-arm{letter}.json"
    p = list(pose or [0.8, -62.2, 53.1, 51.6, 45.2, 49.0])
    (prep / fname).write_text(json.dumps({"chunks": {"home": [p, p]}}), encoding="utf-8")


def _seed_live_hold(bench, monkeypatch, *, arm="arm_a", pid=515151, state=None, pwm=None, holding=False, label="HOLD", age_s=0.5):
    import bench_record_recover as brr
    import cell_arm_lease

    _seed_home_library(bench.prep, arm=arm)
    letter = {"arm_a": "a", "arm_b": "b", "arm_s": "s"}[arm]
    io_dir = bench.prep / f"chunk-io-{letter}"
    io_dir.mkdir(parents=True, exist_ok=True)
    live_p = io_dir / "live.json"
    hold_p = io_dir / "hold.json"
    live_p.write_text(json.dumps({
        "pid": pid,
        "holding": holding,
        "fault": None,
        "human_hold_latched": True,
        "torque_hold_commanded": True,
        "state": list(state or [0.6, -62.5, 53.0, 51.7, 45.1, 49.2]),
        "health": {"pwm": list(pwm or [0, -10, 12, 5, 0, 0])},
    }), encoding="utf-8")
    now = time.time()
    os.utime(live_p, (now - age_s, now - age_s))
    hold_p.write_text(json.dumps({
        "pid": pid,
        "hold": True,
        "label": label,
        "error": f"{label}: near home but never still; a person must support the arm, then kill -USR2 the runner",
    }), encoding="utf-8")
    bench.manual.write_text(json.dumps({
        "arm": arm,
        "kind": "home_hold",
        "runner_pid": pid,
        "reason": f"{arm} 홈용 record_session이 HOLD(토크 유지, PID {pid}) 상태로 보류되었습니다",
        "detail": f"{label}: near home but never still",
    }), encoding="utf-8")
    if not cell_arm_lease.status(arm).get(arm):
        cell_arm_lease.claim(arm, pid=pid, now=1.0)
        cell_arm_lease.hold(arm, "HOLD", pid=pid)
    monkeypatch.setattr(brr, "_pid_is_chunk_runner", lambda p: p == pid)


def test_safe_folded_hold_blocks_unfolded_stale_holding_and_partial_stop(tmp_path, monkeypatch):
    from bench_record_auto_recover import safe_folded_hold

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    _seed_live_hold(bench, monkeypatch, state=[0.6, -62.5, 53.0, 51.7, 45.1, 49.2])
    mh = bench.manual_hold_info()
    ok, _ = safe_folded_hold(bench.prep, "arm_a", mh)
    assert ok is True

    # Unfolded/extended arm MUST fail closed
    _seed_live_hold(bench, monkeypatch, state=[0.0, -5.0, 10.0, 20.0, 0.0, 49.0])
    ok_unf, why_unf = safe_folded_hold(bench.prep, "arm_a", bench.manual_hold_info())
    assert ok_unf is False and ("홈 자세" in why_unf or "접히지" in why_unf)

    # Holding gripper MUST fail closed
    _seed_live_hold(bench, monkeypatch, holding=True)
    ok_h, why_h = safe_folded_hold(bench.prep, "arm_a", bench.manual_hold_info())
    assert ok_h is False and "파지" in why_h

    # PARTIAL_GUARD_STOP MUST fail closed
    _seed_live_hold(bench, monkeypatch, label="PARTIAL_GUARD_STOP")
    ok_p, why_p = safe_folded_hold(bench.prep, "arm_a", bench.manual_hold_info())
    assert ok_p is False and "PARTIAL_GUARD_STOP" in why_p

    # Stale live.json MUST fail closed
    _seed_live_hold(bench, monkeypatch, age_s=25.0)
    ok_s, why_s = safe_folded_hold(bench.prep, "arm_a", bench.manual_hold_info())
    assert ok_s is False and "오래" in why_s


def test_auto_recover_endpoint_chains_folded_release_units_and_baseline(tmp_path, monkeypatch):
    import bench_record_recover as brr
    import cell_arm_lease

    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    pid = 616161
    _seed_live_hold(bench, monkeypatch, arm="arm_a", pid=pid)
    bench._remember(["rosy-omx-cell-task-worker.service"])
    bench._retry_at = bench.clock() + 100
    bench.state = {"status": "homing", "name": "home-arm_a", "error": "HOLD: near home but never still"}

    alive = [True]
    monkeypatch.setattr(brr, "_pid_is_chunk_runner", lambda p: alive[0] and p == pid)
    monkeypatch.setattr(brr, "_pid_alive", lambda p: alive[0] and p == pid)

    killed = []
    def fake_kill(p, sig):
        killed.append((p, sig))
        alive[0] = False
        proof = bench.prep / "chunk-io-a" / "released.json"
        proof.write_text(json.dumps({"pid": pid, "torque_off_confirmed": True, "t": time.time()}), encoding="utf-8")

    monkeypatch.setattr(brr.os, "kill", fake_kill)
    monkeypatch.setattr(brr, "hold_arm_lock", lambda a: (object(), None))
    monkeypatch.setattr(brr, "release", lambda h: None)
    base_cmds = []
    monkeypatch.setattr(brr.subprocess, "run", lambda cmd, **kw: (base_cmds.append(cmd), SimpleNamespace(returncode=0, stdout='{"configuration_verified": true, "error": null}\n', stderr=''))[1])

    diag = bench.status()["recovery"]
    assert diag["auto_recover"]["eligible"] is True and diag["auto_recover"]["arm"] == "arm_a"

    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/api/recover/auto",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json", "X-Bench": "1"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
    finally:
        srv.shutdown()
        srv.server_close()

    assert body["ok"] is True
    assert body["steps"] == ["runner_released_folded", "manual_hold_cleared", "baseline_restored"]
    assert body["status"]["status"] == "idle"
    assert body["status"]["manual_hold"] is None and body["status"]["recovery"] is None
    assert not bench.manual.exists() and not bench.pending.exists()
    assert not cell_arm_lease.status("arm_a").get("arm_a")
    assert ("start", "rosy-omx-cell-task-worker.service") in calls
    assert any("--baseline" in c for c in base_cmds[0]) and killed


def test_auto_recover_refuses_unfolded_hold_without_signalling_runner(tmp_path, monkeypatch):
    import bench_record_recover as brr

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    pid = 717171
    _seed_live_hold(bench, monkeypatch, arm="arm_a", pid=pid, state=[12.0, 5.0, -10.0, 30.0, 0.0, 49.0])
    killed = []
    monkeypatch.setattr(brr.os, "kill", lambda p, s: killed.append((p, s)))

    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/api/recover/auto",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json", "X-Bench": "1"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()
    assert all(sig == 0 for _, sig in killed) and bench.manual.exists()


def test_cell_map_camera_overlay_polygons_and_overlay_js_served(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    cm = bench.cell_map()
    ov = cm["camera_overlay"]
    assert ov["frame"] == {"width": 640, "height": 480} and ov["arm_a_side"] == "right"
    spots = ov["spots"]
    for key in ("belt", "stand", "pallet", "ship-h1r0", "ship-h1r2", "ship-h2r0", "tmp-a-1", "tmp-b-1"):
        assert len(spots[key]) == 4
    # Arm A is on the right side of the top camera frame: h1r0 x > h1r2 x, and h1 is above h2 (closer to belt)
    assert spots["ship-h1r0"][0][0] > spots["ship-h1r2"][0][0]
    assert spots["ship-h1r0"][0][1] < spots["ship-h2r0"][0][1]
    assert spots["tmp-a-1"][0][0] > spots["tmp-b-1"][0][0]

    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/", timeout=5) as r:
            html = r.read().decode("utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/bench_record_overlay.js", timeout=5) as r2:
            assert r2.status == 200 and b"renderCamGoalOverlay" in r2.read()
    finally:
        srv.shutdown()
        srv.server_close()
    assert "/bench_record_overlay.js" in html


def test_choices_shared_instance_id_routes_arm_a_and_arm_s_to_distinct_cameras(tmp_path, monkeypatch):
    from collection_profile import digest

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    dev_dir = tmp_path / "devs"
    dev_dir.mkdir()
    devs = {}
    for name in ("d435", "side-usb", "a-wrist", "s-top", "s-wrist"):
        p = dev_dir / name
        p.write_text("ok", encoding="utf-8")
        devs[name] = str(p)
    ra = {"type": "omx_follower", "id": "omx_follower_arm", "port": "/dev/ttyA", "cameras": {
        "top": {"type": "opencv", "index_or_path": devs["d435"]},
        "side": {"type": "opencv", "index_or_path": str(dev_dir / "missing-arm_a_jieli")},
        "wrist": {"type": "opencv", "index_or_path": devs["a-wrist"]},
    }}
    rs = {"type": "omx_follower", "id": "omx_follower_arm", "port": "/dev/ttyS", "cameras": {
        "top": {"type": "opencv", "index_or_path": devs["s-top"]},
        "wrist": {"type": "opencv", "index_or_path": devs["s-wrist"]},
    }}
    (bench.prep / "record-config-arm-a.json").write_text(json.dumps({"robot": ra}), encoding="utf-8")
    (bench.prep / "record-config-arm-s-live.json").write_text(json.dumps({"robot": rs}), encoding="utf-8")
    for letter, arm_id, rob in (("a", "arm_a", ra), ("s", "arm_s", rs)):
        (bench.prep / f"arm-{letter}-robot-profile.json").write_text(json.dumps({
            "schema": "rosy.omx-cell-robot-profile.v1", "device_id": arm_id, "instance_id": "omx_follower_arm",
            "robot_config_sha256": digest(rob), "operating_envelope_path": "envelope.json", "work_dir": "work",
        }), encoding="utf-8")
    reg_dir = tmp_path / "home" / ".config" / "rosy"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "omx-cameras.json").write_text(json.dumps({"cameras": [
        {"role": "top", "enabled": True, "device": devs["d435"]},
        {"role": "side", "enabled": True, "device": devs["side-usb"]},
        {"role": "arm_a_wrist", "enabled": True, "device": devs["a-wrist"]},
        {"role": "arm_s_top", "enabled": False, "device": devs["s-top"]},
        {"role": "arm_s_wrist", "enabled": True, "device": devs["s-wrist"]},
    ]}), encoding="utf-8")
    ch = bench.choices()
    meta_a = ch["config_meta"]["record-config-arm-a.json"]
    assert meta_a["camera_issues"] == []
    assert any("side:" in rb and devs["side-usb"] in rb for rb in meta_a["camera_rebinds"])
    assert not any("arm_s_" in rb for rb in meta_a["camera_rebinds"])
    assert "record-config-arm-a.json" in ch["arm_bindings"]["arm_a"]["configs"]


def test_link_zero_episodes_ends_as_stopped_safe_while_recorded_episodes_seal(tmp_path, monkeypatch):
    from bench_record_link import link_zero_episodes
    from test_omx_bench_record import finished

    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    ds0 = tmp_path / "ds-zero"
    ds1 = tmp_path / "ds-one"

    def make_popen(ep_count):
        def _popen(command, cwd, **kwargs):
            commands.append(command)
            if command[1].endswith("record_session.py"):
                ds = ds1 if ep_count > 0 else ds0
                (ds / "meta").mkdir(parents=True, exist_ok=True)
                (ds / "meta" / "info.json").write_text(json.dumps({"total_episodes": ep_count}), encoding="utf-8")
                if ep_count > 0:
                    (ds / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
                    (ds / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"PAR1")
                cfg_p = Path(cwd) / "cfg.json"
                cfg_p.write_text(json.dumps({"dataset": {"root": str(ds)}}), encoding="utf-8")
                (Path(cwd) / "link").mkdir(exist_ok=True)
                (Path(cwd) / "link" / "state.json").write_text(json.dumps({"state": "waiting", "episode": ep_count}), encoding="utf-8")
                (Path(cwd) / "session.json").write_text(json.dumps({"safe_end": True, "config": str(cfg_p)}), encoding="utf-8")
                (Path(cwd) / "clean-end.json").write_text(json.dumps({"clean": True}), encoding="utf-8")
            return SimpleNamespace(wait=lambda timeout=None: 0, poll=lambda: 0, returncode=0, send_signal=lambda s: None)
        return _popen

    bench.popen = make_popen(0)
    bench.prepare(dict(body, name="zero-ep-link"))
    st0 = finished(bench)
    assert st0["status"] == "stopped_safe" and link_zero_episodes(st0["folder"], {"config": "cfg.json"}) is True
    assert not any(c[1].endswith("record_seal.py") for c in commands)

    commands.clear()
    bench.popen = make_popen(1)
    bench.prepare(dict(body, name="one-ep-link"))
    st1 = finished(bench)
    assert st1["status"] == "sealed" and any(c[1].endswith("record_seal.py") for c in commands)
    assert link_zero_episodes(st1["folder"], {"config": "cfg.json"}) is False
    assert link_zero_episodes(tmp_path, {}) is False


def test_arm_a_ik_planner_builds_joint_bounded_pallet_replay(tmp_path, monkeypatch):
    import importlib.util

    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    cdir = bench.prep / "cell-arm-a"
    cdir.mkdir(parents=True)
    (bench.prep / "cell-arm-a-stack.json").write_text(json.dumps({
        "joint_min": {"wrist_roll.pos": -31.0},
        "joint_max": {"wrist_roll.pos": 62.0, "wrist_flex.pos": 56.0},
    }), encoding="utf-8")
    (cdir / "auto-pallet-0-160_127.json").write_text(json.dumps({
        "gripper_closed": 49.0,
        "transit": {"shoulder_lift.pos": -27.0, "elbow_flex.pos": 18.0, "wrist_flex.pos": 46.0},
        "chunks": {
            "above_pick": [[20.6, 5.8, 5.0, 39.3, 20.5, 55.0]],
            "descend_pick": [[20.6, 10.4, 7.0, 58.0, -40.0, 55.0]],
            "grasp_pick": [[20.6, 10.4, 7.0, 32.7, 20.5, 47.0]],
            "lift_pick": [[20.6, 6.8, 5.7, 37.6, 20.5, 49.0]],
            "above_place": [[17.9, -10.1, 18.2, 42.0, 17.9, 49.0]],
            "descend_place": [[17.9, -6.0, 22.2, 33.9, 17.9, 49.0]],
            "release_place": [[17.9, -6.0, 22.2, 33.9, 17.9, 55.0]],
            "lift_place": [[17.9, -11.4, 13.4, 48.0, 17.9, 55.0]],
            "home": [[0.8, -62.2, 53.1, 51.6, 45.2, 49.0]],
        },
    }), encoding="utf-8")
    res = bench.pipeline_generate_replay({
        "source_type": "ik_planner", "arm": "arm_a", "origin": "pallet", "target_slot": "ship-h1r0-l0",
    })
    assert res["replay_id"] == "replays/pipe-ik-planner-arm_a.json"
    rp = bench.prep / res["replay_id"]
    traj = json.loads(rp.read_text(encoding="utf-8"))
    frames = traj["frames"]
    assert all(f[3] <= 56.0 and -31.0 <= f[4] <= 62.0 and f[5] >= 49.0 for f in frames)
    monkeypatch.syspath_prepend(str(ROOT / "middleware/devices/omx/adapter"))
    spec = importlib.util.spec_from_file_location("teach_trajectory", ROOT / "deploy/robot/omx/teach_trajectory.py")
    tt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tt)
    assert tt.load(rp, fps=30)["sha256"]


def _seed_incident_hold(bench, tmp_path, monkeypatch, *, fault_text, latched=None, folded=True, stops=None, extra_facts=None):
    import omx_incident

    inc_root = tmp_path / "omxhome" / "incidents"
    inc_root.mkdir(parents=True, exist_ok=True)
    hold_p = inc_root / "HOLD-arm_a.json"
    hold_p.write_text(json.dumps({"reason": f"1 open arm incident(s): {fault_text}", "incident_ids": ["f" * 32]}), encoding="utf-8")
    inc_dir = bench.prep / "incidents" / "20261123T142906-arm_a"
    inc_dir.mkdir(parents=True, exist_ok=True)
    rec = bench.prep / "faults" / "omx_follower_arm-20261123T052904-126e8b.json"
    facts = {
        "safe_end": True, "latched": latched or {}, "folded": folded, "caps_restored": True,
        "torque_after": {str(i): 0 for i in range(11, 17)}, "windup_hits": [], "stops": stops or [],
        "flagged": [{"command": "run goto above_pick", "error": None, "fault": fault_text, "caught": None, "person_needed": None}],
        "flagged_total": 1, "fault_records": [str(rec)], "fault_records_total": 1,
        "fault_record_kinds": [{"fault": "stale effort sample (>0.5 seconds)", "stop_reasons": []}],
        **(extra_facts or {}),
    }
    (inc_dir / "incident.json").write_text(json.dumps({"schema": "rosy.omx-incident.v1", "arm": "arm_a", "facts": facts}), encoding="utf-8")
    (bench.prep / "cell-arm-a-stack.json").write_text(json.dumps({"arm_id": "arm_a", "plan_path": "plan.json"}), encoding="utf-8")
    tok = tmp_path / "home" / ".config" / "rosy" / "cell-a-ai-assessor.token"
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text("assessor-secret", encoding="utf-8")
    os.chmod(tok, 0o600)
    monkeypatch.setattr(omx_incident, "held", lambda arm: json.loads(hold_p.read_text())["reason"] if arm == "arm_a" and hold_p.is_file() else None)
    monkeypatch.setattr(omx_incident, "outbox", lambda arm: [])
    return hold_p, tok


def test_auto_recover_clears_clean_stale_effort_incident_via_reassess(tmp_path, monkeypatch):
    import omx_incident

    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    hold_p, tok = _seed_incident_hold(bench, tmp_path, monkeypatch, fault_text="session ended: ValueError: stale effort sample (>0.5 seconds)")
    monkeypatch.setattr(omx_incident, "sync_hold_from_fleet", lambda arm: not hold_p.is_file())
    clear_cmds = []

    def fake_clear(cmd, *, cwd, env, timeout=60):
        clear_cmds.append((cmd, cwd, env))
        hold_p.unlink(missing_ok=True)
        return SimpleNamespace(returncode=0, stdout='{"arm": "arm_a", "cleared": ["' + ("f" * 32) + '"], "held": false}\n', stderr="")

    monkeypatch.setattr(bench, "_run_incident_clear", fake_clear)
    diag = bench.status()["recovery"]
    assert diag["auto_recover"]["eligible"] is True
    assert "clear_fleet_incident" in diag["auto_recover"]["steps"]

    res = bench.auto_recover({"arm": "arm_a"})
    assert res["ok"] is True and "incident_cleared:arm_a" in res["steps"]
    assert res["status"]["recovery"] is None
    assert len(clear_cmds) == 1 and "--reassess" in clear_cmds[0][0] and str(tok) in clear_cmds[0][0]
    assert ("stop", "rosy-omx-observer@arm_a.service") in calls and ("start", "rosy-omx-observer@arm_a.service") in calls


def test_auto_recover_restarts_observer_on_reassess_refusal_and_blocks_unsafe_incidents(tmp_path, monkeypatch):
    import omx_incident

    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    hold_p, _ = _seed_incident_hold(bench, tmp_path, monkeypatch, fault_text="session ended: ValueError: stale effort sample (>0.5 seconds)")
    monkeypatch.setattr(omx_incident, "sync_hold_from_fleet", lambda arm: False)
    monkeypatch.setattr(bench, "_run_incident_clear", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="AI_CLEAR_REPEAT_LIMIT"))
    with pytest.raises(ValueError, match="AI_CLEAR_REPEAT_LIMIT"):
        bench.auto_recover({"arm": "arm_a"})
    assert ("stop", "rosy-omx-observer@arm_a.service") in calls
    assert ("start", "rosy-omx-observer@arm_a.service") in calls
    assert hold_p.is_file()

    for kwargs in (
        {"latched": {"13": {"hw_error": 32, "bits": ["overload"]}}},
        {"folded": False},
        {"stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]},
        {"extra_facts": {"fault_record_kinds": [{"fault": "stale effort sample (>0.5 seconds)", "stop_reasons": ["overload"]}]}},
    ):
        hp, _ = _seed_incident_hold(bench, tmp_path, monkeypatch, fault_text="session ended: ValueError: stale effort sample (>0.5 seconds)", **kwargs)
        ar = bench.status()["recovery"]["auto_recover"]
        assert ar["eligible"] is False
        with pytest.raises(ValueError):
            bench.auto_recover({"arm": "arm_a"})
        assert hp.is_file()


def test_auto_recover_and_manual_clear_support_return_home_and_activating_observer(tmp_path, monkeypatch):
    import omx_incident

    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    orig_run = bench.run

    def act_run(*args):
        if args == ("is-active", "rosy-omx-observer@arm_a.service"):
            return SimpleNamespace(returncode=3, stdout="activating\n", stderr="")
        return orig_run(*args)

    bench.run = act_run
    hold_p, _ = _seed_incident_hold(bench, tmp_path, monkeypatch, fault_text="session ended: ValueError: stale effort sample (>0.5 seconds)")
    monkeypatch.setattr(omx_incident, "sync_hold_from_fleet", lambda arm: not hold_p.is_file())
    monkeypatch.setattr(bench, "_run_incident_clear", lambda cmd, **kw: (hold_p.unlink(missing_ok=True), SimpleNamespace(returncode=0, stdout="", stderr=""))[1])
    home_calls = []
    monkeypatch.setattr(bench, "go_home", lambda req: (home_calls.append(req), {**bench.status(), "home_moved": [req["arm"]]})[1])
    res = bench.auto_recover({"arm": "arm_a", "return_home": True, "include_leader": True})
    assert res["ok"] is True and res["returned_home"] is True and "returned_home" in res["steps"]
    assert home_calls == [{"arm": "arm_a", "include_leader": True, "fold_unfolded": True}]
    assert ("stop", "rosy-omx-observer@arm_a.service") in calls and ("start", "rosy-omx-observer@arm_a.service") in calls

    hold_p2, _ = _seed_incident_hold(bench, tmp_path, monkeypatch, fault_text="session ended: ValueError: stale effort sample (>0.5 seconds)")
    monkeypatch.setattr(omx_incident, "sync_hold_from_fleet", lambda arm: not hold_p2.is_file())
    monkeypatch.setattr(bench, "go_home", lambda req: (_ for _ in ()).throw(ValueError("경로 차단: 상단 카메라 장애물")))
    fail_res = bench.auto_recover({"arm": "arm_a", "return_home": True})
    assert fail_res["ok"] is False and fail_res["recovered"] is True and fail_res["home_failed"] is True
    assert "장애물" in fail_res["next_action"]

    bench.manual.write_text(json.dumps({"arm": "arm_a", "reason": "manual check"}), encoding="utf-8")
    monkeypatch.setattr(bench, "go_home", lambda req: (home_calls.append(req), {**bench.status(), "home_moved": [req["arm"]]})[1])
    clr_ok = bench.clear_manual_hold({"confirmed": True, "return_home": True})
    assert clr_ok["recovered"] is True and clr_ok["returned_home"] is True
    assert home_calls[-1] == {"arm": "arm_a", "include_leader": True, "fold_unfolded": True}

    bench.manual.write_text(json.dumps({"arm": "arm_a", "reason": "manual check"}), encoding="utf-8")
    monkeypatch.setattr(bench, "go_home", lambda req: (_ for _ in ()).throw(ValueError("HOLD: torque kept")))
    clr_fail = bench.clear_manual_hold({"confirmed": True, "return_home": True})
    assert clr_fail["recovered"] is True and clr_fail["home_failed"] is True and "SIGUSR2" in clr_fail["next_action"]
