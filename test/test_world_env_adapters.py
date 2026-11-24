"""Tests for ROSY World single-contract environment adapters, parity invariants, and parallel world monitor."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications" / "world"))
sys.path.insert(0, str(ROOT / "tools" / "sim"))
sys.path.insert(0, str(ROOT / "test"))

import bridge_real_fleet  # noqa: E402
import observe_isaac  # noqa: E402
import observe_pinky  # noqa: E402
import serve  # noqa: E402
import world_env_adapter as adapter  # noqa: E402
import world_swarm  # noqa: E402
from test_world_factory_stream import _make_closed_fixture  # noqa: E402
from world_factory_timeline import compile_timeline  # noqa: E402


def _make_bundle(tmp_path: Path) -> Path:
    closed, site_map, reg = _make_closed_fixture(tmp_path)
    tl = compile_timeline(closed, site_map, reg, include_extended=True)
    bundle = tmp_path / "bundle"
    (bundle / "data").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "app.js").write_text("", encoding="utf-8")
    (bundle / "SHA256SUMS.txt").write_text("", encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({
        "inputs": {"site-map/world_261026_v7_active.json": {"sha256": tl["site_map_sha256"]}},
    }), encoding="utf-8")
    (bundle / "data" / "factory-timeline.json").write_text(json.dumps(tl), encoding="utf-8")
    return bundle


def test_parity_contract_enforces_only_env_differs_and_fails_closed() -> None:
    tray = adapter.load_pinky_tray_fingerprint(
        ROOT / "middleware/devices/pinky/profile/config/geometry.yaml"
    )
    assert tray["pocket_z_m"] == pytest.approx(0.04425, abs=1e-4)
    ref = adapter.build_parity_fingerprint(
        site_map_sha256="ab" * 32,
        registration_sha256="cd" * 32,
        has_cargo_tray=True,
        cargo_tray=tray,
    )
    ok = adapter.verify_parity(ref, dict(ref))
    assert ok["ok"] and ok["map_match"] and ok["robot_match"] and ok["tray_match"]

    assert not adapter.verify_parity(ref, None)["ok"]
    assert "site_map_sha256_mismatch" in adapter.verify_parity(ref, {**ref, "site_map_sha256": "0" * 64})["reasons"]
    assert "missing_pinky_cargo_tray" in adapter.verify_parity(ref, {**ref, "has_cargo_tray": False})["reasons"]
    assert "fleet_robots_mismatch" in adapter.verify_parity(ref, {**ref, "fleet_robots": {"pinkys": ["rosy_45"], "arms": []}})["reasons"]
    bad_tray = dict(tray, pocket_z_m=0.060)
    assert not adapter.verify_parity(ref, {**ref, "cargo_tray": bad_tray})["tray_match"]


def test_real_adapter_is_read_only_and_never_fakes_replay(tmp_path: Path) -> None:
    tray = adapter.load_pinky_tray_fingerprint(ROOT / "middleware/devices/pinky/profile/config/geometry.yaml")
    parity = adapter.build_parity_fingerprint(site_map_sha256="ab" * 32, has_cargo_tray=True, cargo_tray=tray)
    real = adapter.create_adapter("real", world_id="real-site", snapshot_path=tmp_path / "missing.json", parity=parity, run_id="real")
    assert real.descriptor()["capabilities"] == []
    assert real.poll_state() is None

    # Replay snapshots must never pass as live Real hardware.
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(json.dumps({"stream_mode": "verified_replay", "observed_at_ms": time.time_ns() // 1_000_000}), encoding="utf-8")
    real2 = adapter.create_adapter("real", world_id="real-site", snapshot_path=replay_file, parity=parity, run_id="real")
    assert real2.poll_state() is None


def test_parallel_worlds_discovery_stream_security_and_control_guards(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    written = world_swarm.publish_once(bundle)
    assert len(written) == 3

    class DummyControl:
        def command(self, body):
            return 200, {"ok": True, "echo": body}

        def status(self):
            return {"ok": True}

    server = serve.make_server(bundle, "127.0.0.1", 0)
    server.sim_control = DummyControl()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        # 1. Registry discovers 3 parallel worlds + verified-replay + real-site.
        with urllib.request.urlopen(f"{origin}/api/worlds", timeout=5) as resp:
            reg = json.loads(resp.read().decode("utf-8"))
        by_id = {w["world_id"]: w for w in reg["worlds"]}
        assert {"isaac-train-01", "mujoco-ab-02", "gazebo-nav-03", "verified-replay", "real-site"} <= set(by_id)
        assert by_id["isaac-train-01"]["status"] == "live" and by_id["isaac-train-01"]["parity"]["ok"]
        assert by_id["isaac-train-01"]["training"]["episode"] >= 148
        assert by_id["real-site"]["status"] == "waiting"

        # 2. Adapter filter returns only matching backend.
        with urllib.request.urlopen(f"{origin}/api/worlds?adapter=isaac", timeout=5) as resp:
            isaac_reg = json.loads(resp.read().decode("utf-8"))
        assert [w["world_id"] for w in isaac_reg["worlds"]] == ["isaac-train-01"]

        # 3. Streaming specific world emits that world's live telemetry.
        with urllib.request.urlopen(f"{origin}/sim/stream?world=isaac-train-01&max_events=1", timeout=5) as resp:
            line = next(l for l in resp.read().decode("utf-8").splitlines() if l.startswith("data: "))
            evt = json.loads(line[6:])
        assert evt["world_id"] == "isaac-train-01" and evt["adapter"] == "isaac" and evt["stream_mode"] == "live"
        assert evt["parity"]["ok"] is True

        # 4. Real stream must emit idle (waiting), never fallback to verified_replay.
        with urllib.request.urlopen(f"{origin}/sim/stream?adapter=real&max_events=1", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "event: idle" in body
        idle_evt = json.loads(next(l[6:] for l in body.splitlines() if l.startswith("data: ")))
        assert idle_evt["stream_mode"] == "waiting" and idle_evt["adapter"] == "real"

        # 5. Path traversal and unknown world fail closed with 400 / 404.
        for bad, expected_code in (("../manifest", 400), ("missing-world-99", 404)):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"{origin}/sim/stream?world={bad}&max_events=1", timeout=5)
            assert exc.value.code == expected_code

        # 6. Mismatched map sha256 fails parity closed.
        world_swarm.publish_once(bundle, inject_mismatch_world="gazebo-nav-03")
        with urllib.request.urlopen(f"{origin}/api/worlds", timeout=5) as resp:
            reg2 = json.loads(resp.read().decode("utf-8"))
        gz = next(w for w in reg2["worlds"] if w["world_id"] == "gazebo-nav-03")
        assert gz["parity"]["ok"] is False and "site_map_sha256_mismatch" in gz["parity"]["reasons"]

        # 7. Real hardware control forbidden (403).
        req = urllib.request.Request(
            f"{origin}/sim/control",
            data=json.dumps({"adapter": "real", "action": "reset"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": origin, "Host": origin.removeprefix("http://")},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 403
    finally:
        server.stop_event.set()
        server.shutdown()
        server.server_close()


def test_http_ingest_token_guards_and_training_hook(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    worlds_dir = tmp_path / "external_worlds"
    canonical_sha = json.loads((bundle / "data" / "factory-timeline.json").read_text(encoding="utf-8"))["site_map_sha256"]
    server = serve.make_server(bundle, "127.0.0.1", 0, worlds_dir=worlds_dir, ingest_token="secret-ingest-1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        sample_state = {
            "schema": "rosy.world.factory-state.v1",
            "stream_mode": "live",
            "adapter": "isaac",
            "run_id": "rl-run-1",
            "site_map_sha256": canonical_sha,
            "fleet_robots": adapter.CANONICAL_FLEET_ROBOTS,
            "has_cargo_tray": True,
            "pinky": {"id": "rosy_45", "pose_m": [0.1, 0.2, 0.0], "yaw_rad": 0.0},
            "pinkys": [
                {"id": "rosy_42", "pose_m": [-0.414, 0.47, 0.0], "yaw_rad": -1.57},
                {"id": "rosy_45", "pose_m": [0.1, 0.2, 0.0], "yaw_rad": 0.0},
                {"id": "rosy_46", "pose_m": [0.032, 0.47, 0.0], "yaw_rad": -1.57},
            ],
            "arms": {k: [0.0] * 6 for k in ("arm_s", "arm_a", "arm_b")},
        }

        # Missing / invalid token fails closed (401 / 403).
        for hdrs, expected in (
            ({"Content-Type": "application/json"}, 401),
            ({"Content-Type": "application/json", "Authorization": "Bearer wrong"}, 403),
        ):
            req = urllib.request.Request(
                f"{origin}/api/worlds/isaac-remote-01",
                data=json.dumps(sample_state).encode("utf-8"),
                headers=hdrs,
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=5)
            assert exc.value.code == expected

        # Non-live replay payload in real adapter is rejected (403).
        req_fake_real = urllib.request.Request(
            f"{origin}/api/worlds/real-site",
            data=json.dumps({**sample_state, "adapter": "real", "stream_mode": "verified_replay"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret-ingest-1"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_fake_real, timeout=5)
        assert exc.value.code == 403

        # Oversized payload rejected (413).
        req_huge = urllib.request.Request(
            f"{origin}/api/worlds/isaac-remote-01",
            data=b"{" + b" " * (serve.MAX_INGEST_BYTES + 10) + b"}",
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret-ingest-1"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req_huge, timeout=5)
        assert exc.value.code == 413

        # TrainingWorldHook pushes cleanly with valid bearer token and discovers via /api/worlds.
        with adapter.TrainingWorldHook(
            world_id="isaac-remote-01",
            backend="isaac",
            run_id="rl-run-1",
            site_map_sha256=canonical_sha,
            world_url=origin,
            token="secret-ingest-1",
            min_interval_s=0.0,
        ) as hook:
            assert hook.publish_step(
                sim_time_s=1.5,
                stage="c2_departure",
                phase="rl_train",
                pinky={"id": "rosy_45", "pose_m": [0.25, 0.3, 0.0], "yaw_rad": 0.4},
                episode=7,
                step=42,
                reward=1.25,
            )

        assert (worlds_dir / "isaac-remote-01.json").is_file()
        with urllib.request.urlopen(f"{origin}/api/worlds", timeout=5) as resp:
            reg = json.loads(resp.read().decode("utf-8"))
        remote_entry = next(w for w in reg["worlds"] if w["world_id"] == "isaac-remote-01")
        assert remote_entry["status"] == "live" and remote_entry["parity"]["ok"] is True
        assert remote_entry["training"]["episode"] == 7

        # DELETE removes the published snapshot.
        reply = adapter.delete_world_snapshot(origin, "isaac-remote-01", token="secret-ingest-1")
        assert reply["ok"] and reply["deleted"]
        assert not (worlds_dir / "isaac-remote-01.json").is_file()
    finally:
        server.stop_event.set()
        server.shutdown()
        server.server_close()


def test_observers_and_real_fleet_bridge_translations_and_fail_closed() -> None:
    site_sha = "cd" * 32
    canonical = {
        "site_map_sha256": site_sha,
        "fleet_robots": adapter.CANONICAL_FLEET_ROBOTS,
        "has_cargo_tray": True,
    }

    isaac_state = observe_isaac.build_world_state(
        run_id="isaac-obs-1",
        world_id="isaac-cell-01",
        state="running",
        sim_time_s=4.2,
        joints=[{"name": "arm_a_joint1", "position_rad": 0.5}],
        objects=[{"id": "rosy_45", "position_m": [0.74, -0.20, 0.0], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}],
        site_map_sha256=site_sha,
        scene="ab",
    )
    assert isaac_state["adapter"] == "isaac" and isaac_state["arms"]["arm_a"][0] == pytest.approx(0.5)
    assert serve.verify_world_parity(canonical, isaac_state)["ok"]

    gz_state = observe_pinky.build_world_state(
        binding={"robot_id": "rosy_42", "run_id": "sim-gz-1"},
        world_id="gazebo-run-01",
        sim_time_s=2.5,
        position=[0.745, -0.207, 0.0],
        yaw=3.14,
        site_map_sha256=site_sha,
    )
    assert gz_state["adapter"] == "gazebo" and gz_state["stage"] == "s3_stop"
    assert serve.verify_world_parity(canonical, gz_state)["ok"]

    # Offline Fleet must fail closed (None), never fabricating live real motion.
    offline_fleet = {"robots": [{"robot_id": "rosy_45", "online": False, "state": {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}}]}
    assert bridge_real_fleet.fleet_state_to_world_state(offline_fleet, site_map_sha256=site_sha) is None

    # Online Fleet maps real robot pose strictly as live `real` adapter.
    online_fleet = {
        "robots": [
            {
                "robot_id": "rosy_45",
                "online": True,
                "state": {
                    "pose": {"x": 0.745, "y": -0.207, "yaw": 3.14159},
                    "battery": {"percent": 82.0},
                    "safety": {"estop": False},
                },
            }
        ]
    }
    real_state = bridge_real_fleet.fleet_state_to_world_state(online_fleet, site_map_sha256=site_sha)
    assert real_state is not None
    assert real_state["adapter"] == "real" and real_state["stream_mode"] == "live"
    assert real_state["pinky"]["id"] == "rosy_45" and real_state["stage"] == "s3_stop"
    assert serve.verify_world_parity(canonical, real_state)["ok"]


def test_world_docker_compose_hardening_and_bounded_logs() -> None:
    world_compose = yaml.safe_load((ROOT / "applications/world/compose.yaml").read_text(encoding="utf-8"))
    for name in ("world", "real-bridge", "sim-swarm"):
        svc = world_compose["services"][name]
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in svc["security_opt"]
        assert svc["logging"]["driver"] == "json-file"
        assert svc["logging"]["options"] == {"max-size": "20m", "max-file": "3"}
    assert any(v.get("target") == "/var/lib/rosy-world/worlds" and v.get("read_only") is False for v in world_compose["services"]["world"]["volumes"])

    site_world = yaml.safe_load((ROOT / "deploy/site/compose.world.yaml").read_text(encoding="utf-8"))
    assert "logging" not in site_world["services"]["fleet"]
    for name in ("world", "world-real-bridge"):
        svc = site_world["services"][name]
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert svc["logging"] == {"driver": "json-file", "options": {"max-size": "20m", "max-file": "3"}}
