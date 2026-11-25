"""Tests for ROSY World single-contract environment adapters, parity invariants, and parallel world monitor."""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.parse
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
from world_state import LIVE_FRESH_MS, REAL_FRESH_MS  # noqa: E402
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


def test_world_registry_and_stream_distinguish_real_freshness_and_synthetic_demo(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    now = time.time_ns() // 1_000_000
    worlds = bundle / "data" / "worlds"
    base = {"schema": "rosy.world.factory-state.v1", "stream_mode": "live"}
    for world_id, adapter_id, mode, age in (
        ("real-site", "real", "live", 5_000),
        ("old-sim", "mujoco", "live", 5_000),
        ("demo", "isaac", "synthetic_demo", 0),
    ):
        serve._atomic_write_json(worlds / f"{world_id}.json", {
            **base, "world_id": world_id, "adapter": adapter_id, "stream_mode": mode, "observed_at_ms": now - age,
        })
    assert (LIVE_FRESH_MS, REAL_FRESH_MS) == (3_000, 10_000)
    for offset, expected in ((0, "live"), (5_001, "stalled")):
        reg = serve.discover_worlds(bundle, now + offset)
        real_entries = [w for w in reg["worlds"] if w["world_id"] == "real-site"]
        assert [w["status"] for w in real_entries] == [expected]
    by_id = {w["world_id"]: w for w in serve.discover_worlds(bundle, now)["worlds"]}
    assert by_id["old-sim"]["status"] == "stalled"
    assert by_id["demo"]["status"] == "synthetic_demo"

    with serve.make_server(bundle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for world_id, mode in (("real-site", "live"), ("demo", "synthetic_demo")):
                url = f"http://127.0.0.1:{server.server_port}/sim/stream?world={world_id}&max_events=1"
                with urllib.request.urlopen(url, timeout=5) as res:
                    assert res.readline() == b"event: state\n"
                    assert json.loads(res.readline()[6:])["stream_mode"] == mode
        finally:
            server.shutdown()
            thread.join()


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
        assert by_id["isaac-train-01"]["status"] == "synthetic_demo" and by_id["isaac-train-01"]["parity"]["ok"]
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
        assert evt["world_id"] == "isaac-train-01" and evt["adapter"] == "isaac" and evt["stream_mode"] == "synthetic_demo"
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
    assert real_state["pinky"]["observed"] is True and real_state["pinky"]["has_cargo"] is False
    assert serve.verify_world_parity(canonical, real_state)["ok"]


def test_real_bridge_keeps_unlocalized_pinky_and_accepts_arm_only_observations() -> None:
    site_sha = "ab" * 32
    fleet = {"gathered_at": 1_710_000_000.125, "robots": [{
        "robot_id": "rosy_42", "online": True, "state_age_s": 3.5,
        "state": {"pose": {"x": 0, "y": 0, "yaw": 0}},
        "localization": {"pose_frame": "odom", "trusted": True},
    }]}
    observed_arm = {"joints_deg": [180, -90, 45, 0, 10, 0], "observed": True, "fresh": False, "age_s": 4.5}
    arms = {"arm_s": {**observed_arm, "source": "boot_default"}, "arm_a": observed_arm}
    snapshot = bridge_real_fleet.fleet_state_to_world_state(fleet, site_map_sha256=site_sha, arm_live_states=arms)
    pinky = snapshot["pinky"]
    assert pinky["id"] == "rosy_42" and pinky["online"] is True
    assert pinky["pose_m"] == [0, 0, 0] and pinky["yaw_rad"] == 0
    assert pinky["observed"] is pinky["localized"] is pinky["has_cargo"] is False
    assert pinky["loc_label"] == "위치 모름" and pinky["state_age_s"] == 3.5
    assert snapshot["fleet_gathered_at_ms"] == 1_710_000_000_125
    assert snapshot["arms_observed"] == {"arm_s": False, "arm_a": True, "arm_b": False}
    assert snapshot["arms_fresh"] == {"arm_s": False, "arm_a": False, "arm_b": False}
    assert snapshot["arms_age_s"]["arm_a"] == 4.5
    assert snapshot["arms"]["arm_a"] == pytest.approx([math.pi, -math.pi / 2, math.pi / 4, 0, math.pi / 18, 0])

    fleet["robots"][0]["localization"] = {"pose_frame": "map", "trusted": False, "label": "미확인"}
    only_pinky = bridge_real_fleet.fleet_state_to_world_state(fleet, site_map_sha256=site_sha)
    assert only_pinky["pinky"]["observed"] is False and only_pinky["pinky"]["loc_label"] == "미확인"
    assert bridge_real_fleet.fleet_state_to_world_state({"robots": []}, site_map_sha256=site_sha, arm_live_states=arms)
    assert bridge_real_fleet.fleet_state_to_world_state(
        {"robots": []}, site_map_sha256=site_sha, arm_live_states={"arm_s": arms["arm_s"]},
    ) is None


def test_world_map_parity_prefers_body_hash_and_reports_versions(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    site_map = bundle / "data" / "site-map.json"
    body = {"label": "현장", "id": "test"}
    sha = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    site_map.write_text(json.dumps({"map": body, "version": 7}), encoding="utf-8")
    canonical = serve._canonical_reference(bundle)
    assert canonical["site_map_body_sha256"] == sha
    site_map.write_text(json.dumps({"sha256": sha.upper(), "map": {}, "version": 7}), encoding="utf-8")
    assert serve._canonical_reference(bundle) == canonical

    fleet = {"robots": [{"robot_id": "rosy_45", "online": True}]}
    snapshot = bridge_real_fleet.fleet_state_to_world_state(
        fleet, site_map_sha256="fe" * 32, active_map={"sha256": sha.upper(), "version": 8},
    )
    assert snapshot["site_map_body_sha256"] == sha and snapshot["site_map_sha256"] == "fe" * 32
    parity = serve.verify_world_parity(canonical, snapshot)
    assert parity["map_match"] and parity["bundle_map_version"] == 7 and parity["live_map_version"] == 8
    assert not serve.verify_world_parity(canonical, {
        **snapshot, "site_map_body_sha256": "12" * 32, "parity": canonical,
    })["map_match"]
    unavailable = serve.verify_world_parity(
        canonical, {**snapshot, "site_map_body_sha256": "invalid", "parity": canonical},
    )
    assert not unavailable["map_match"]
    assert unavailable["reasons"] == ["live_site_map_unavailable"]


@pytest.mark.parametrize(("args", "timeout"), [([], 10.0), (["--fleet-timeout", "4.5"], 4.5),
                                                (["--fleet-timeout", "99"], 30.0), (["--fleet-timeout", "0"], 1.0)])
def test_real_bridge_cli_timeout_and_optional_fleet_reads(tmp_path: Path, monkeypatch, args, timeout) -> None:
    fleet = {"robots": [{"robot_id": "rosy_45", "online": True}]}
    calls = []

    def urlopen(req, *, timeout, context):
        path = urllib.parse.urlsplit(req.full_url).path
        calls.append((path, timeout, req.get_header("Authorization"), context))
        if path == "/api/fleet/state":
            return io.BytesIO(json.dumps(fleet).encode("utf-8"))
        raise urllib.error.HTTPError(req.full_url, 404, "Not found", {}, None)

    monkeypatch.setenv("TEST_FLEET_TOKEN", "viewer-token")
    monkeypatch.setattr(sys, "argv", [
        "bridge_real_fleet", "--once", "--fleet-url", "https://fleet.test", "--worlds-dir", str(tmp_path),
        "--fleet-token-env", "TEST_FLEET_TOKEN", "--ca-file", "test-ca.pem", *args,
    ])
    monkeypatch.setattr(bridge_real_fleet.ssl, "create_default_context", lambda *, cafile: cafile)
    monkeypatch.setattr(bridge_real_fleet.urllib.request, "urlopen", urlopen)
    bridge_real_fleet.main()
    assert calls == [
        (path, limit, "Bearer viewer-token", "test-ca.pem")
        for path, limit in (
            ("/api/fleet/state", timeout), ("/api/fleet/pipeline/cell-tasks", 2.0), ("/api/fleet/site-map/active", 2.0),
        )
    ]
    snapshot = json.loads((tmp_path / "real-site.json").read_bytes())
    assert snapshot["site_map_body_sha256"] is None
    assert not any(snapshot["arms_observed"].values())


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


def test_world_factory_actors_node_unit_tests(tmp_path: Path) -> None:
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run(
        [node, "--test", "--test-reporter=spec", str(ROOT / "applications/world/test/factory-actors.test.mjs")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
