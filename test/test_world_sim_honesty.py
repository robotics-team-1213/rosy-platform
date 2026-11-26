"""Simulation honesty contracts: no unbacked capability, arm-motion or cargo claims (PR-W4).

Covers the empty default env capabilities, the swarm's `synthetic_demo` tagging,
the training hooks' static rest arms + `arms_observed` + `has_cargo=False`,
`world_factory_close` rejecting non-passing downstream evidence, the MuJoCo
physics smoke script, and the live-feeds.js D-136 vision lease flow.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
for rel in ("tools/sim", "operations/fleet", "test"):
    entry = str(ROOT / rel)
    if entry not in sys.path:
        sys.path.insert(0, entry)

import world_env_adapter as adapter  # noqa: E402
import world_swarm  # noqa: E402
import world_training_hooks as training_hooks  # noqa: E402
from factory_isaac_handoff import prepare  # noqa: E402
from test_world_factory_pipeline import _make_prefix, _write_json  # noqa: E402
from world_factory_close import close_factory_flow  # noqa: E402

PHYSICS_SMOKE = ROOT / "tools" / "sim" / "world_physics_smoke.py"
LIVE_FEEDS = ROOT / "applications" / "world" / "web" / "live-feeds.js"


def _hook(tmp_path: Path, world_id: str = "honest-01") -> adapter.TrainingWorldHook:
    return adapter.TrainingWorldHook(
        world_id=world_id, backend="mujoco", run_id=f"{world_id}-run", site_map_sha256="ab" * 32,
        worlds_dir=tmp_path, min_interval_s=0.0,
    )


def _published(tmp_path: Path, world_id: str = "honest-01") -> dict:
    return json.loads((tmp_path / f"{world_id}.json").read_text(encoding="utf-8"))


def test_env_adapters_and_hook_default_to_no_capabilities(tmp_path: Path) -> None:
    parity = adapter.build_parity_fingerprint(site_map_sha256="ab" * 32, has_cargo_tray=True)
    mujoco = adapter.create_adapter(
        "mujoco", world_id="w1", snapshot_path=tmp_path / "w1.json", parity=parity, run_id="r1",
    )
    assert mujoco.descriptor()["capabilities"] == []
    explicit = adapter.create_adapter(
        "isaac", world_id="w2", snapshot_path=tmp_path / "w2.json", parity=parity, run_id="r2",
        capabilities=("reset",),
    )
    assert explicit.descriptor()["capabilities"] == ["reset"]  # explicit claims stay allowed
    hook = adapter.TrainingWorldHook(
        world_id="w3", backend="gazebo", run_id="r3", site_map_sha256="ab" * 32, min_interval_s=0.0,
    )
    assert hook.descriptor["capabilities"] == []


def test_publish_step_pads_unobserved_pinkys_and_defaults_arms_unobserved(tmp_path: Path) -> None:
    assert _hook(tmp_path).publish_step(
        sim_time_s=1.0, stage="ab_stack", phase="t",
        pinky={"id": "rosy_45", "pose_m": [0.1, 0.2, 0.0], "yaw_rad": 0.0},
        arms={"arm_a": [0.0] * 6},
    )
    state = _published(tmp_path)
    by_id = {item["id"]: item for item in state["pinkys"]}
    assert by_id["rosy_45"]["observed"] is True
    for rid in ("rosy_42", "rosy_46"):
        assert by_id[rid]["observed"] is False and by_id[rid]["has_cargo"] is False
    assert state["arms_observed"] == {"arm_s": False, "arm_a": False, "arm_b": False}


def test_swarm_snapshots_report_synthetic_demo_and_no_capabilities() -> None:
    keyframe = {
        "time_s": 0.0, "stage": "c2_departure", "simulator": "gazebo", "phase": "run",
        "pinky": {"id": "rosy_45", "pose_m": [0.0, 0.0, 0.0], "yaw_rad": 0.0},
        "pinkys": [], "arms": {}, "cargo": {"zone": "s3", "pose_m": [0.0, 0.0, 0.0], "yaw_rad": 0.0},
        "cell_ab": {"active_arm": None, "active_step": None, "stacked": []},
    }
    timeline = {"duration_s": 1.0, "keyframes": [keyframe],
                "fleet_robots": adapter.CANONICAL_FLEET_ROBOTS, "stages": []}
    parity = adapter.build_parity_fingerprint(site_map_sha256="ab" * 32, has_cargo_tray=True)
    snap = world_swarm.build_worker_snapshot(world_swarm.DEFAULT_WORKERS[0], timeline, parity, 3, 0.5)
    assert snap["schema"] == adapter.FACTORY_STATE_SCHEMA
    assert snap["stream_mode"] == "synthetic_demo"
    assert snap["env"]["capabilities"] == []
    assert snap["env"]["parity"] == parity


def test_train_progress_streams_real_numbers_without_fabricated_motion(tmp_path: Path) -> None:
    hook = _hook(tmp_path, "train-01")
    progress = training_hooks.make_experiment_train_progress(hook, method="act", total_steps=10)
    progress({"step": 3, "loss": 0.42})
    state = _published(tmp_path, "train-01")
    assert state["training"]["step"] == 3 and state["training"]["loss"] == 0.42
    assert state["training"]["sim_fps"] > 0
    assert state["arms"] == {key: list(values) for key, values in training_hooks.DEFAULT_REST_ARMS.items()}
    assert state["arms_observed"] == {"arm_s": False, "arm_a": False, "arm_b": False}
    assert state["cargo"] == {
        "zone": "unknown", "pose_m": list(training_hooks.DEFAULT_S3_PINKY["pose_m"]),
        "yaw_rad": training_hooks.DEFAULT_S3_PINKY["yaw_rad"], "observed": False,
    }
    assert state["pinky"]["has_cargo"] is False
    progress({"step": 9, "loss": 0.4})
    assert _published(tmp_path, "train-01")["arms"] == state["arms"]  # arms never move


def test_mujoco_two_arm_hook_reports_observed_arms_only_and_no_pinky_cargo(tmp_path: Path) -> None:
    hook = _hook(tmp_path, "cell-01")
    world = types.SimpleNamespace(q={"arm_a": slice(0, 6)})  # arm_b missing; no layout/pose -> no cargo observation
    on_frame = training_hooks.make_mujoco_two_arm_hook(
        world, hook, reg=training_hooks.DEFAULT_SITE_FROM_CELL, task_name="stack", episode_ref=[1],
    )
    on_frame(types.SimpleNamespace(qpos=[0.05] * 6), "arm_a:s1")
    state = _published(tmp_path, "cell-01")
    assert state["arms_observed"] == {"arm_s": False, "arm_a": True, "arm_b": False}
    assert state["arms"]["arm_a"] == [0.05] * 6
    assert state["pinky"]["has_cargo"] is False
    assert state["cargo"]["observed"] is False


def test_isaac_map_rl_step_does_not_claim_cargo(tmp_path: Path) -> None:
    training_hooks.publish_isaac_map_rl_step(
        _hook(tmp_path, "rl-01"), elapsed=1.2, phase="train", pose=[0.3, 0.4, 0.1], epoch=2, step=7, reward=1.5,
    )
    state = _published(tmp_path, "rl-01")
    assert state["pinky"]["has_cargo"] is False
    assert state["training"]["episode"] == 2 and state["training"]["reward"] == 1.5


@pytest.mark.parametrize(
    ("slot", "payload", "raw"),
    [
        (2, {}, False),
        (2, {"pass": False}, False),
        (2, {"status": "fail", "passed": True}, False),
        (2, [1, 2], False),
        (2, {"stage": "arm_s_to_belt"}, False),  # no passing indicator at all
        (0, {"pass": False}, False),
        (1, {"pass": False}, False),
        (2, None, "not-json{"),
    ],
)
def test_close_factory_flow_rejects_non_passing_downstream_evidence(
    tmp_path: Path, slot: int, payload: object, raw: object,
) -> None:
    prefix_dir = tmp_path / "prefix"
    prefix, site_map = _make_prefix(prefix_dir, [0.745, -0.207, math.pi])
    _write_json(prefix_dir / "isaac-intake.json", prepare(prefix, site_map))
    good = tmp_path / "good.json"
    _write_json(good, {"stage": "x", "passed": True})
    bad = tmp_path / "bad.json"
    if raw:
        bad.write_text(str(raw), encoding="utf-8")
    else:
        bad.write_text(json.dumps(payload), encoding="utf-8")
    evidence = [good, good, good]
    evidence[slot] = bad
    with pytest.raises(ValueError, match="evidence"):
        close_factory_flow(prefix_dir, *evidence, tmp_path / "out")


def _mujoco_available() -> bool:
    try:
        import mujoco  # noqa: F401  a broken native install also means "not installed here"
        return True
    except Exception:
        return False


def test_physics_smoke_help_and_syntax() -> None:
    compile(PHYSICS_SMOKE.read_text(encoding="utf-8"), str(PHYSICS_SMOKE), "exec")
    proc = subprocess.run(
        [sys.executable, str(PHYSICS_SMOKE), "--help"], capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0
    assert "--steps" in proc.stdout and "--out" in proc.stdout


@pytest.mark.skipif(not _mujoco_available(), reason="mujoco is not installed on this host")
def test_physics_smoke_steps_a_finite_scene(tmp_path: Path) -> None:
    out = tmp_path / "physics-smoke.json"
    proc = subprocess.run(
        [sys.executable, str(PHYSICS_SMOKE), "--steps", "300", "--out", str(out)],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["ok"] is True and summary["engine"] == "mujoco" and summary["steps"] == 300
    assert summary["dt_s"] > 0 and summary["sim_time_s"] >= 0
    assert json.loads(out.read_text(encoding="utf-8")) == summary


def test_live_feeds_field_camera_uses_d136_vision_lease() -> None:
    source = LIVE_FEEDS.read_text(encoding="utf-8")
    assert source.count("\r") == 0  # LF-only contract
    assert len(source.splitlines()) <= 600
    assert 'const FLEET_VISION_SOURCES = "/api/fleet/vision/sources";' in source
    assert 'const FLEET_VISION_LEASE = "/api/fleet/vision/lease";' in source
    # The source list is queried before any lease is acquired and the ceiling source is preferred.
    assert source.index("await fetch(FLEET_VISION_SOURCES") < source.index("await issueFieldLease(session, sourceId")
    assert "pickCeilingSource(session.sources)" in source
    assert "JSON.stringify({ source_id: sourceId })" in source
    # The frame URL is validated same-origin and fetched with the lease as the only credential.
    assert "new URL(framePath, location.origin)" in source
    assert "path.origin !== location.origin" in source
    assert 'credentials: "omit"' in source
    assert "Authorization: `Bearer ${session.lease.token}`" in source
    # The lease is reused until ~15 s before expires_in_s.
    assert "const FLEET_LEASE_MARGIN_MS = 15000;" in source
    assert "session.lease.expiresAt - FLEET_LEASE_MARGIN_MS" in source
    # 401/403/503 stop the 400 ms polling loop with an honest status instead of retrying.
    assert "res.status === 401 || res.status === 403" in source
    assert "res.status === 503" in source
    assert "로그인 필요" in source and "카메라 미리보기 비활성" in source
    assert "if (cameraSession === session && !session.halted)" in source
    # Only a 404 from /api/fleet/vision/sources falls back to the bundled ./data/field-live.jpg.
    assert "res.status === 404" in source
    assert "fleet: true" in source
