"""Tests for canonical cell_map provenance, live redacted logs, custom goals, defaults reset, and topbar dedupe."""
import json
from pathlib import Path
import re
import threading
import urllib.request

import pytest

from test_omx_bench_record import ROOT, bench_record, finished, _setup


def test_cell_map_endpoint_reads_canonical_yaml_and_site_map(tmp_path, monkeypatch):
    bench, _, _, _ = _setup(tmp_path, monkeypatch)
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
    bench, body, _, _ = _setup(tmp_path, monkeypatch)
    teleop_dir = tmp_path / "home/.cache/huggingface/lerobot/calibration/teleoperators/omx_leader"
    mount_p = teleop_dir / "arm_a_leader.mount.json"
    mount_p.write_text(json.dumps({
        "mount": {"shoulder_pan": -2048},
        "follower_floor": {"shoulder_lift": 1200},
        "gripper": {"leader_closed": 1900, "leader_open": 2900, "follower_closed": 2000, "follower_open": 2800},
    }), encoding="utf-8")

    # Edit grip map & speed & custom caps, plus leave a safety manual marker that MUST NOT be deleted
    bench.save_grip_map({"arm": "arm_a", "leader_closed": 1800, "leader_open": 2600, "follower_closed": 2100, "follower_open": 2500})
    bench.set_teleop_speed({"arm": "arm_a", "stage": 90})
    assert "gripper_factory" not in json.loads(mount_p.read_text(encoding="utf-8"))  # never pollute .mount.json!

    manual = bench.manual
    manual.write_text('{"reason": "keep-safety-marker"}', encoding="utf-8")

    # Reset to factory preset -> speed cleared (25 deg/s), original grip restored while mount/follower_floor preserved, manual marker kept
    out = bench.reset_defaults({"preset": "factory", "scope": "all", "arm": "arm_a"})
    assert out["ok"] is True
    assert not (bench.prep / "teleop-speed-arm_a.json").exists()
    after_mount = json.loads(mount_p.read_text(encoding="utf-8"))
    assert after_mount["mount"] == {"shoulder_pan": -2048}
    assert after_mount["follower_floor"] == {"shoulder_lift": 1200}
    assert after_mount["gripper"] == {"leader_closed": 1900, "leader_open": 2900, "follower_closed": 2000, "follower_open": 2800}
    assert manual.exists()
    manual.unlink()

    # Busy refusal while recording
    bench.state = {"status": "recording", "arm": "arm_a"}
    with pytest.raises(ValueError, match="진행 중"):
        bench.reset_defaults({"preset": "recommended", "scope": "all", "arm": "arm_a"})


def test_ui_workspace_no_duplicate_pills_live_log_and_reset_controls():
    omx_dir = ROOT / "deploy/robot/omx"
    html = (omx_dir / "bench_record.html").read_text(encoding="utf-8")
    css = (omx_dir / "bench_record.css").read_text(encoding="utf-8")
    js = "\n".join((omx_dir / f).read_text(encoding="utf-8") for f in (
        "bench_record_ui.js", "bench_record_map.js", "bench_record_log_reset.js", "bench_record_app.js",
    ))

    assert 'id="rail-arm-pills"' not in html
    for marker in ('id="sec-live-log"', 'id="live-log-body"', 'id="goal-provenance"',
                   'id="goal-custom-panel"', 'id="sb-factory-reset-btn"', 'id="factory-reset-btn"',
                   'id="hdr-reset-retry-btn"', '/bench_record_log_reset.js'):
        assert marker in html, marker
    assert not re.search(r'\b(?:transition|animation)\b|@keyframes', css)
    assert '.identity{flex:1 1 auto;overflow:hidden}' in css
    assert 'loadCellMap' in js and '/api/defaults/reset' in js and 'getCustomTaskOverride' in js
