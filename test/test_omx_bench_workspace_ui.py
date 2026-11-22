"""Tests for canonical cell_map provenance, live redacted logs, custom goals, defaults reset, homing hold recovery, episode review/delete, and UI grouping."""
import json
from pathlib import Path
import re
import threading
import urllib.request

import pytest

from test_omx_bench_record import ROOT, SimpleNamespace, bench_record, finished, _arm_s_live_files, _home_with_stages, _setup


def test_cell_map_endpoint_reads_canonical_yaml_and_site_map(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    (bench.prep / "tasks" / "teach.yaml").write_text(
        "schema: rosy.omx-task-card.v1\ntask_id: teach-one\nrevision: 1\nsingle_task: Teach\n"
        "record:\n  repo_id: local/teach\n  root_prefix: /tmp/omx\n  episode_time_s: 30\n  reset_time_s: 10\n  num_episodes: 5\n"
        "known_limits:\n  - Keep wrist under 56 deg\n",
        encoding="utf-8",
    )
    (bench.prep / "cell-arm-a-stack.json").write_text(json.dumps({
        "cameras": {"top": {"height_m": 0.596, "warp_to_reference": {"measured": "2026-11-19T02:40:50"}}},
        "sites": {"belt": {"place": [0.1, 0.2]}, "ship-h1r0-l0": {"place": [0.2, 0.3]}},
    }), encoding="utf-8")
    cm = bench.cell_map()
    assert cm["schema"] == "rosy.cell-site-map.v1"
    assert cm["tier_height_mm"] == 32.4
    codes = {s["code"]: s for s in cm["spot_catalog"]}
    assert codes["ship-h1r0-l1"]["site_id"] == "yard:r1-s2-t2"
    assert codes["ship-h1r0-l1"]["height_mm"] == 32.4
    assert codes["stand"]["site_id"] == "stand:r1-s1-t1"
    assert "stack" in cm["sim_tasks"] and cm["calibrated_sites"]["arm_a"]["top_height_m"] == 0.596
    assert cm["task_provenance"]["tasks/teach.yaml"]["repo_id"] == "local/teach"
    assert "Keep wrist under 56 deg" in cm["task_provenance"]["tasks/teach.yaml"]["known_limits"]
    assert any(s["path"] == "shared/web/cell-site-map.json" and s["exists"] for s in cm["sources"])

    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/cell_map", timeout=5) as r:
            assert r.status == 200 and json.loads(r.read())["schema"] == "rosy.cell-site-map.v1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_live_logs_redacts_secrets_and_reads_bench_log(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    sess = bench.prep / "sessions" / "20261123-010000-test"
    sess.mkdir(parents=True)
    (sess / "bench.log").write_text(
        "\x1b[32mINFO start\x1b[0m hf_SecretTokenValue12345\n"
        "WARN Bearer my_secret_bearer_tok\n",
        encoding="utf-8",
    )
    bench._log_event("bench", "info", "수동 이벤트 hf_AnotherSecret999999")
    res = bench.live_logs(limit=50)
    joined = "\n".join(r["text"] for r in res["entries"])
    assert "hf_SecretTokenValue12345" not in joined
    assert "hf_AnotherSecret999999" not in joined
    assert "my_secret_bearer_tok" not in joined
    assert "hf_<REDACTED>" in joined and "Bearer <REDACTED>" in joined
    assert res["log_file"] == "bench.log"
    assert any(r["level"] == "warn" for r in res["entries"])


def test_custom_goal_synthesizes_effective_task_card_while_refusing_plain_swap_without_task(tmp_path, monkeypatch):
    bench, body, _, commands = _setup(tmp_path, monkeypatch)
    no_task = dict(body, task="")
    with pytest.raises(ValueError, match="작업 카드 선택"):
        bench.start(dict(no_task, task_override={"swap_pick_place": True}))
    with pytest.raises(ValueError, match="같을 수 없습니다"):
        bench.start(dict(no_task, task_override={"custom": True, "origin": "belt", "target_slot": "belt"}))

    res = bench.start(dict(no_task, task_override={
        "custom": True, "origin": "belt", "target_slot": "ship-h1r0-l0", "single_task": "Custom pick and place test",
    }))
    state = finished(bench)
    assert state["status"] == "sealed"
    assert res["task_id"] == "custom-belt-to-ship-h1r0-l0"
    tc_idx = commands[0].index("--task-card") + 1
    card = json.loads(Path(commands[0][tc_idx]).read_text(encoding="utf-8"))
    assert card["schema"] == "rosy.omx-task-card.v1"
    assert card["layout"]["origin"] == "belt" and card["layout"]["target_slot"] == "ship-h1r0-l0"
    assert card["single_task"] == "Custom pick and place test"


def test_factory_defaults_snapshot_and_safe_reset(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    teleop_dir = tmp_path / "home/.cache/huggingface/lerobot/calibration/teleoperators/omx_leader"
    mount_p = teleop_dir / "arm_a_leader.mount.json"
    mount_p.write_text(json.dumps({
        "mount": {"shoulder_pan": -2048},
        "follower_floor": {"shoulder_lift": 1200},
        "gripper": {"leader_closed": 1900, "leader_open": 2900, "follower_closed": 2000, "follower_open": 2800},
    }), encoding="utf-8")

    bench.save_grip_map({"arm": "arm_a", "leader_closed": 1800, "leader_open": 2600, "follower_closed": 2100, "follower_open": 2500})
    bench.set_teleop_speed({"arm": "arm_a", "stage": 90})
    assert "gripper_factory" not in json.loads(mount_p.read_text(encoding="utf-8"))

    manual = bench.manual
    manual.write_text('{"reason": "keep-safety-marker"}', encoding="utf-8")

    out = bench.reset_defaults({"preset": "factory", "scope": "all", "arm": "arm_a"})
    assert out["ok"] is True
    assert not (bench.prep / "teleop-speed-arm_a.json").exists()
    after_mount = json.loads(mount_p.read_text(encoding="utf-8"))
    assert after_mount["mount"] == {"shoulder_pan": -2048}
    assert after_mount["follower_floor"] == {"shoulder_lift": 1200}
    assert after_mount["gripper"] == {"leader_closed": 1900, "leader_open": 2900, "follower_closed": 2000, "follower_open": 2800}
    assert manual.exists()
    manual.unlink()

    bench.state = {"status": "recording", "arm": "arm_a"}
    with pytest.raises(ValueError, match="진행 중"):
        bench.reset_defaults({"preset": "recommended", "scope": "all", "arm": "arm_a"})


def test_go_home_stops_worker_and_diagnoses_clear_manual_hold(tmp_path, monkeypatch):
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    _arm_s_live_files(bench)
    orig_run = bench.run

    def run_with_worker(*args):
        res = orig_run(*args)
        if args[0] == "list-units":
            res.stdout = res.stdout + "\nrosy-omx-cell-task-worker.service loaded active running worker"
        return res

    bench.run = run_with_worker
    _home_with_stages(bench, monkeypatch, tmp_path, [("home", None)])
    bench.go_home({"arm": "arm_s", "at_bench": True})
    assert ("stop", "rosy-omx-cell-task-worker.service") in calls
    assert ("start", "rosy-omx-cell-task-worker.service") in calls

    calls.clear()
    _home_with_stages(bench, monkeypatch, tmp_path, [("home", None)])
    io_s = bench.prep / "chunk-io-s"
    io_s.mkdir(exist_ok=True)
    (io_s / "hold.json").write_text(json.dumps({"pid": 999999, "hold": True, "error": "HOLD: human hold already latched"}), encoding="utf-8")
    (bench.prep / ".bench-runs").mkdir(exist_ok=True)

    def held_popen(command, cwd, **kw):
        (bench.prep / ".bench-runs" / "home-arm_s.log").write_text(
            'motor-health follower: skip\n{"command": "human-hold", "ok": true}\n{"step": "RUNNER_HELD", "report": {"pid": 999999, "error": "HOLD: human hold already latched"}}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(poll=lambda: 0, wait=lambda timeout=None: 75, returncode=75, send_signal=lambda s: None, kill=lambda: None)

    bench.popen = held_popen
    with pytest.raises(ValueError, match="사람이 팔 상태를 확인"):
        bench.go_home({"arm": "arm_s", "at_bench": True})
    st = bench.status()
    mh = st["manual_hold"]
    assert mh["active"] is True and mh["arm"] == "arm_s" and mh["runner_pid"] == 999999
    assert mh["worker_human_hold"] is True and mh["log_tail"] == ['{"command": "human-hold", "ok": true}', '{"step": "RUNNER_HELD", "report": {"pid": 999999, "error": "HOLD: human hold already latched"}}']

    with pytest.raises(ValueError, match="arm_supported_confirmed"):
        bench.release_held_runner({"arm": "arm_s", "pid": 999999})
    with pytest.raises(ValueError, match="confirmed=true"):
        bench.clear_manual_hold({})
    bench.procs = lambda: ["python record_session.py"]
    with pytest.raises(ValueError, match="아직 실행 중"):
        bench.clear_manual_hold({"confirmed": True})
    bench.procs = lambda: []
    cleared = bench.clear_manual_hold({"confirmed": True})
    assert cleared["status"] == "idle" and cleared["manual_hold"] is None and not bench.manual.exists()


def test_recovery_center_dead_lease_baseline_units_and_ack(tmp_path, monkeypatch):
    import bench_record_recover as brr
    import cell_arm_lease
    bench, _, calls, _ = _setup(tmp_path, monkeypatch)
    # 1) clear_manual_hold resets leader_hold so _idle() stays idle and enforces force_dead_lease on dead held leases
    cell_arm_lease.claim("arm_a", pid=999999, now=1.0)
    cell_arm_lease.hold("arm_a", "runner HOLD", pid=999999)
    bench.leader_hold = "stale leader hold"
    bench.manual.write_text('{"reason":"stuck","arm":"arm_a"}', encoding="utf-8")
    rec_diag = bench.status()["recovery"]
    assert rec_diag["has_issues"] is True and "arm_a" in rec_diag["dead_lease_arms"] and rec_diag["baseline_needed"] is True
    with pytest.raises(ValueError, match="죽은 러너"):
        bench.clear_manual_hold({"confirmed": True})
    st = bench.clear_manual_hold({"confirmed": True, "force_dead_lease": True})
    assert st["status"] == "idle" and bench.leader_hold == "" and not cell_arm_lease.status("arm_a").get("arm_a")

    # 2) recover_restore_units refuses while manual check exists, succeeds when removed
    bench._remember(["rosy-omx-observer@arm_a.service"])
    bench._retry_at = bench.clock() + 100
    assert bench.status()["recovery"]["can_restore_units"] is True
    bench.manual.write_text('{"reason":"wait"}', encoding="utf-8")
    with pytest.raises(ValueError, match="수동 확인 보류"):
        bench.recover_restore_units({})
    bench.manual.unlink()
    st = bench.recover_restore_units({})
    assert ("start", "rosy-omx-observer@arm_a.service") in calls and not bench.pending.exists()

    # 3) recover_baseline verifies commissioning_limits --baseline under arm lock
    ran = []
    monkeypatch.setattr(brr, "hold_arm_lock", lambda a: (object(), None))
    monkeypatch.setattr(brr, "release", lambda h: None)
    monkeypatch.setattr(brr.subprocess, "run", lambda cmd, **kw: (ran.append(cmd), SimpleNamespace(returncode=0, stdout='{"configuration_verified": true, "error": null}\n', stderr=''))[1])
    bench.state = {"status": "failed", "error": "caps are not the baseline"}
    res_b = bench.recover_baseline({"arm": "arm_a"})
    assert res_b["ok"] is True and any("--baseline" in c for c in ran[0]) and res_b["status"]["status"] == "idle"

    # 4) ack_bench_error resets ended error state to idle, refuses during active recording
    bench.state = {"status": "unsafe_or_failed", "error": "abort"}
    assert bench.status()["recovery"]["can_ack_error"] is True
    assert bench.ack_bench_error()["status"] == "idle"
    bench.state = {"status": "recording", "arm": "arm_a"}
    with pytest.raises(ValueError, match="진행 중인 작업"):
        bench.ack_bench_error()


def test_episode_review_do_not_train_and_delete(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    ds = tmp_path / "home" / "rosy-data" / "omx-leader" / "demo-ds-1"
    (ds / "meta").mkdir(parents=True)
    (ds / "data" / "chunk-000").mkdir(parents=True)
    (ds / "videos" / "observation.images.top" / "chunk-000").mkdir(parents=True)
    (ds / "videos" / "observation.images.top" / "chunk-000" / "file-000.mp4").write_bytes(b"MP4DATA")
    (ds / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"PAR1")
    (ds / "meta" / "info.json").write_text(json.dumps({"total_episodes": 3, "total_frames": 300, "fps": 30}), encoding="utf-8")

    info = bench.dataset_episodes("demo-ds-1")
    assert info["total_episodes"] == 3 and info["cameras"] == ["top"]
    assert bench.resolve_dataset_video("demo-ds-1", "top", 0, 0).read_bytes() == b"MP4DATA"

    rated = bench.rate_episode({"dataset": "demo-ds-1", "episode": 1, "rating": "bad", "note": "dropped box"})
    assert rated["episodes"][1]["rating"] == "bad" and rated["summary"]["bad"] == 1
    assert bench.lerobot_datasets()[0]["review_summary"]["bad"] == 1

    dnt = bench.set_dataset_do_not_train({"dataset": "demo-ds-1", "do_not_train": True, "reason": "bad_take"})
    assert dnt["do_not_train"] is True and (ds / "DO_NOT_TRAIN.txt").is_file()
    (ds / "DO_NOT_TRAIN.txt").write_text("guard abort\n", encoding="utf-8")
    with pytest.raises(ValueError, match="하드웨어 가드"):
        bench.set_dataset_do_not_train({"dataset": "demo-ds-1", "do_not_train": False})

    def fake_prune(ds_folder, indices, staging, repo_id):
        (staging / "meta").mkdir(parents=True)
        (staging / "data" / "chunk-000").mkdir(parents=True)
        (staging / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"PAR1")
        (staging / "meta" / "info.json").write_text(json.dumps({"total_episodes": 2, "total_frames": 200, "fps": 30}), encoding="utf-8")

    bench.rate_episode({"dataset": "demo-ds-1", "episode": 2, "rating": "good", "note": "clean"})
    bench._prune_lerobot_episodes = fake_prune
    pruned = bench.delete_dataset_episodes({"dataset": "demo-ds-1", "episodes": [1], "confirm": True})
    assert pruned["remaining_episodes"] == 2
    assert pruned["episodes_info"]["episodes"][1]["rating"] == "good"  # ep#2 shifted to ep#1
    assert len(list((ds.parent / ".trash").glob("demo-ds-1-before-del-1ep*"))) == 1

    all_del = bench.delete_dataset_episodes({"dataset": "demo-ds-1", "episodes": [0, 1], "confirm": True})
    assert all_del["deleted_all"] is True and not ds.exists()


def test_dataset_episodes_parses_real_static_episodes_int_count_schema(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    ds = tmp_path / "home" / "rosy-data" / "omx-leader" / "demo-real-static"
    (ds / "meta").mkdir(parents=True)
    (ds / "meta" / "info.json").write_text(json.dumps({"total_episodes": 5, "total_frames": 500, "fps": 30}), encoding="utf-8")
    (ds / "static_episodes.json").write_text(json.dumps({"episodes": 5, "static": [0, 1, 3], "threshold": 1.0}), encoding="utf-8")

    srv = bench_record.make_server(bench, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/dataset/episodes?dataset=demo-real-static", timeout=5) as r:
            assert r.status == 200
            body = json.loads(r.read())
    finally:
        srv.shutdown()
        srv.server_close()
    assert [e["index"] for e in body["episodes"] if e["static"]] == [0, 1, 3]


def test_diagnose_manual_hold_detects_live_runner_after_service_restart(tmp_path, monkeypatch):
    import bench_record_recover as brr
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
    bench.state = {"status": "idle"}
    bench.manual.write_text(json.dumps({"reason": "arm_a 홈용 record_session이 정상 종료되지 않았습니다"}), encoding="utf-8")
    io_a = bench.prep / "chunk-io-a"
    io_a.mkdir(exist_ok=True)
    (io_a / "hold.json").write_text(json.dumps({"pid": 424242, "hold": True, "error": "HOLD: human hold already latched"}), encoding="utf-8")
    (io_a / "live.json").write_text(json.dumps({"pid": 424242, "human_hold_latched": True, "torque_hold_commanded": True, "state": [0.0, -62.0, 55.0, 55.0, 40.0, 49.0]}), encoding="utf-8")
    (bench.prep / ".bench-runs").mkdir(exist_ok=True)
    (bench.prep / ".bench-runs" / "home-arm_a.log").write_text('{"command": "human-hold"}\n{"step": "RUNNER_HELD"}\n', encoding="utf-8")
    monkeypatch.setattr(brr, "_pid_is_chunk_runner", lambda p: p == 424242)
    bench.procs = lambda: ["python chunk_runner.py --io chunk-io-a"]

    mh = bench.status()["manual_hold"]
    assert mh["active"] is True and mh["arm"] == "arm_a" and mh["runner_pid"] == 424242
    assert mh["runner_alive"] is True and mh["human_hold_latched"] is True and mh["torque_hold_commanded"] is True
    assert mh["can_release_runner"] is True and mh["can_clear"] is False and mh["log_file"] == "home-arm_a.log"


def test_ui_workspace_no_duplicate_pills_live_log_reset_review_and_clusters():
    omx_dir = ROOT / "deploy/robot/omx"
    html = (omx_dir / "bench_record.html").read_text(encoding="utf-8")
    css = (omx_dir / "bench_record.css").read_text(encoding="utf-8")
    js = "\n".join((omx_dir / f).read_text(encoding="utf-8") for f in (
        "bench_record_ui.js", "bench_record_map.js", "bench_record_log_reset.js", "bench_record_review.js", "bench_record_app.js",
    ))

    assert 'id="rail-arm-pills"' not in html
    for marker in ('id="sec-live-log"', 'id="live-log-body"', 'id="goal-provenance"',
                   'id="goal-custom-panel"', 'id="sb-factory-reset-btn"', 'id="factory-reset-btn"',
                   'id="hdr-reset-retry-btn"', '/bench_record_log_reset.js',
                   'id="manual-hold-card"', 'id="ev-episode-review"', '/bench_record_review.js',
                   'id="mh-quick-actions"', 'class="tool-cluster"', 'class="ops-cluster'):
        assert marker in html, marker
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)
    assert '.identity{flex:1 1 auto;overflow:hidden}' in css
    assert 'loadCellMap' in js and '/api/defaults/reset' in js and 'getCustomTaskOverride' in js
    assert '/api/dataset/episode/rate' in js and '/api/manual_hold/clear' in js
    assert '/api/recover/baseline' in js and "st?.status==='homing'&&(st?.error||st?.manual_hold?.active)" in js
