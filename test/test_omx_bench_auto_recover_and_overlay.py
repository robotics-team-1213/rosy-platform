"""Tests for safety-gated auto_recover (folded-only runner release) and top-camera Pick->Place goal overlay."""
import json
import os
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
