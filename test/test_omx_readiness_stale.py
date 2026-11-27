"""Readiness never reports an old arm row as the current state (2026-11-27 arm_b: board gone, still "folded")."""
import json
import time

import test_omx_stale_latch as base

FOLDED = [0.0, -58.0, 50.0, 50.0, -5.0, 46.0]


def _runner(tmp_path, *, live_t, health_age=0.0, board=True):
    runner = base._cell(tmp_path, live_t=live_t)
    (tmp_path / "chunk-io-b" / "live.json").write_text(json.dumps({"chunk": None, "state": FOLDED, "t": live_t}))
    health = tmp_path / "mh" / "arm_b.json"
    doc = json.loads(health.read_text())
    doc["observed_at"] -= health_age
    health.write_text(json.dumps(doc))
    device = tmp_path / "openrb-by-id"
    if board:
        device.write_text("")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "omx-observer-arm_b.env").write_text(f"ROSY_OBSERVER_DEVICE={device}\n")
    runner.observer_env_dir = tmp_path / "env"
    return runner


def test_a_fresh_live_row_is_the_current_state(tmp_path):
    info, blocks = base._summary(_runner(tmp_path, live_t=time.time(), health_age=3600))
    assert info["folded"] is True and info["state_unknown"] is None and blocks == []


def test_an_old_live_row_is_current_only_when_motor_health_proves_folded_now(tmp_path):
    info, blocks = base._summary(_runner(tmp_path, live_t=time.time() - 3600))
    assert info["folded"] is True and info["state_unknown"] is None and blocks == []


def test_old_sources_are_unknown_with_the_last_observation_and_refuse(tmp_path):
    old = time.time() - 3600
    info, blocks = base._summary(_runner(tmp_path, live_t=old, health_age=1800))
    assert info["folded"] is None and blocks == ["arm_b:state_unknown"]
    assert info["state_unknown"]["reason"] == "stale"
    assert old + 1700 < info["state_unknown"]["last_observed_at"] < old + 1900


def test_a_missing_board_is_unknown_even_with_a_just_written_row(tmp_path):
    info, blocks = base._summary(_runner(tmp_path, live_t=time.time(), board=False))
    assert info["folded"] is None and info["state_unknown"]["reason"] == "board_missing"
    assert blocks == ["arm_b:state_unknown"]


def test_no_source_at_all_is_never_observed(tmp_path):
    runner = _runner(tmp_path, live_t=time.time())
    (tmp_path / "chunk-io-b" / "live.json").unlink()
    (tmp_path / "mh" / "arm_b.json").unlink()
    info, blocks = base._summary(runner)
    assert info["folded"] is None and blocks == ["arm_b:state_unknown"]
    assert info["state_unknown"] == {"reason": "never_observed", "last_observed_at": None}
