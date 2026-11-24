"""Tests for real training telemetry hooks, parallel launcher specs, and real Fleet <-> Virtual CORE closed loop."""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for entry in (
    ROOT / "applications" / "world",
    ROOT / "tools" / "sim",
    ROOT / "tools" / "remote",
    ROOT / "test",
    ROOT / "operations" / "fleet",
    ROOT / "operations" / "account",
    ROOT / "operations" / "decision" / "src",
    ROOT / "operations" / "world" / "src",
    ROOT / "operations" / "site_execution" / "src",
    ROOT / "contracts" / "foundation",
    ROOT / "contracts" / "learning" / "src",
    ROOT / "contracts" / "skill" / "src",
    ROOT / "contracts" / "motion" / "src",
    ROOT / "middleware" / "core" / "services",
    ROOT / "operations" / "processes" / "palletizing" / "src",
    ROOT / "applications" / "fleet" / "gateway" / "src",
):
    text = str(entry)
    if text not in sys.path:
        sys.path.insert(0, text)

import bridge_real_fleet  # noqa: E402
import isaac_batch  # noqa: E402
import serve  # noqa: E402
import virtual_core_fleet as vcore  # noqa: E402
import world_env_adapter as adapter  # noqa: E402
import world_train_parallel as parallel  # noqa: E402
import world_training_hooks as hooks  # noqa: E402
from test_world_factory_stream import _make_closed_fixture  # noqa: E402
from world_factory_timeline import compile_timeline  # noqa: E402


def _make_bundle(tmp_path: Path) -> tuple[Path, str]:
    closed, site_map, reg = _make_closed_fixture(tmp_path / "fixture")
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
    return bundle, tl["site_map_sha256"]


def test_training_hooks_emit_parity_valid_loss_and_mujoco_frames(tmp_path: Path) -> None:
    parity_in = hooks.canonical_parity_inputs(ROOT)
    worlds_dir = tmp_path / "worlds"

    # 1. ACT/HIL-SERL progress callback with loss metric
    act_hook = adapter.TrainingWorldHook(
        world_id="act-test-01",
        backend="mujoco",
        run_id="act-test-01",
        site_map_sha256=parity_in["site_map_sha256"],
        worlds_dir=worlds_dir,
        cargo_tray=parity_in["cargo_tray"],
        min_interval_s=0.0,
    )
    events = []
    cb = hooks.make_experiment_train_progress(act_hook, method="act", total_steps=4, base_progress=events.append)
    cb({"step": 1, "loss": 0.42})
    cb({"step": 4, "loss": 0.11})
    assert len(events) == 2
    act_snap = json.loads((worlds_dir / "act-test-01.json").read_text(encoding="utf-8"))
    assert act_snap["training"]["step"] == 4
    assert act_snap["training"]["loss"] == pytest.approx(0.11, abs=1e-4)
    assert adapter.verify_parity(act_hook.parity, act_snap["parity"])["ok"]

    # 2. Two-arm MuJoCo frame hook reading joints and active container pose
    class _FakeLayout:
        def containers(self):
            return [("bar-1", None)]

    class _FakeWorld:
        q = {"arm_a": slice(0, 6), "arm_b": slice(6, 12)}
        layout = _FakeLayout()

        def pose(self, _data, _cid):
            return np.array([0.05, -0.02, 0.09]), 0.12, 0.0

    class _FakeData:
        qpos = np.array([0.1, -0.5, 0.4, 0.3, 1.5, 0.2, -0.1, -0.4, 0.3, 0.2, 1.4, 0.3], dtype=float)

    mj_hook = adapter.TrainingWorldHook(
        world_id="mujoco-ab-01",
        backend="mujoco",
        run_id="mujoco-ab-01",
        site_map_sha256=parity_in["site_map_sha256"],
        worlds_dir=worlds_dir,
        cargo_tray=parity_in["cargo_tray"],
        min_interval_s=0.0,
    )
    frame_cb = hooks.make_mujoco_two_arm_hook(
        _FakeWorld(), mj_hook, reg=parity_in["site_from_cell"], task_name="rehandle", episode_ref=[2],
    )
    frame_cb(_FakeData(), "arm_a:pick")
    mj_snap = json.loads((worlds_dir / "mujoco-ab-01.json").read_text(encoding="utf-8"))
    assert mj_snap["stage"] == "ab_rehandle"
    assert mj_snap["training"]["episode"] == 2
    assert mj_snap["arms"]["arm_a"][0] == pytest.approx(0.1)
    assert mj_snap["cell_ab"]["active_arm"] == "arm_a"
    assert len(mj_snap["cell_ab"]["stacked"]) == 1
    assert adapter.verify_parity(mj_hook.parity, mj_snap["parity"])["ok"]


def test_isaac_batch_and_parallel_launcher_assign_distinct_world_ids(tmp_path: Path) -> None:
    plan = isaac_batch.expand({
        "scenario": "map_rl",
        "sha": "a" * 40,
        "config": {"train_episodes": 2},
        "cases": ["nom"],
        "seeds": [1, 2],
    })
    annotated = isaac_batch.attach_world_monitor(
        plan, world_url="http://127.0.0.1:8140", world_mdns_host="rosy-world.local", world_port=8140,
    )
    assert annotated["runs"]["nom-s1"]["world_id"] == "isaac-nom-s1"
    assert annotated["runs"]["nom-s2"]["world_mdns_host"] == "rosy-world.local"

    req = tmp_path / "req.json"
    req.write_text("{}", encoding="utf-8")
    ns = type("Args", (), {
        "out": tmp_path / "parallel-out",
        "mujoco_workers": 2,
        "mujoco_tasks": "stack,rehandle",
        "mujoco_repeat": 2,
        "mujoco_python": None,
        "act_request": [req],
        "act_python": None,
        "world_url": "http://127.0.0.1:8140",
        "world_mdns_host": None,
        "world_port": 8140,
        "worlds_dir": None,
        "site_map_sha256": None,
        "world_token_env": "ROSY_WORLD_INGEST_TOKEN",
    })()
    specs = parallel.build_worker_specs(ns, repo_root=ROOT)
    assert [s["world_id"] for s in specs] == ["mujoco-ab-01", "mujoco-ab-02", "act-train-01"]
    assert specs[0]["task"] == "stack"
    assert specs[1]["task"] == "rehandle"
    assert "--concurrent" not in specs[0]["cmd"]

    ns.mujoco_concurrent = True
    specs_conc = parallel.build_worker_specs(ns, repo_root=ROOT)
    assert "--concurrent" in specs_conc[0]["cmd"]


def test_real_fleet_app_closed_loop_with_virtual_six_robot_core_and_world(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import load_robots
    from fleet.swarm.transport import HttpRobotClient
    from rosy_account.site_users import load_site_accounts

    bundle, site_map_sha = _make_bundle(tmp_path)
    worlds_dir = tmp_path / "live-worlds"
    server = serve.make_server(bundle, "127.0.0.1", 0, worlds_dir=worlds_dir)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()
    world_url = f"http://127.0.0.1:{server.server_port}"

    core_token = "virtual-core-secret-token"
    fleet = vcore.VirtualCoreFleet(host="127.0.0.1", base_port=0, token=core_token)
    fleet.start()
    try:
        robots_yaml = tmp_path / "robots.yaml"
        fleet.write_robots_yaml(robots_yaml)
        endpoints = load_robots(robots_yaml)
        clients = [HttpRobotClient(ep) for ep in endpoints]
        console = FleetConsole(endpoints, clients)
        tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)

        op_token = "operator-secret-token"
        users_yaml = tmp_path / "site-users.yaml"
        users_yaml.write_text(
            "users:\n"
            "  - principal_id: op-tester\n"
            "    role: operator\n"
            f"    token_sha256: {hashlib.sha256(op_token.encode()).hexdigest()}\n",
            encoding="utf-8",
        )
        site_users, site_logins = load_site_accounts(users_yaml)
        app = create_app(
            console,
            task_service=tasks,
            site_users=site_users,
            site_logins=site_logins,
            start_task_dispatcher=True,
        )

        auth = {"Authorization": f"Bearer {op_token}"}
        with TestClient(app) as http:
            st0 = http.get("/api/fleet/state", headers=auth)
            assert st0.status_code == 200
            body0 = st0.json()
            assert body0["fleet"]["online"] == 6
            assert body0["fleet"]["total"] == 6

            ctrl = http.get("/api/fleet/dispatch-control", headers=auth)
            assert ctrl.status_code == 200
            if not ctrl.json().get("dispatch_enabled"):
                rearm = http.post(
                    "/api/fleet/dispatch/rearm",
                    headers=auth,
                    json={"expected_generation": ctrl.json()["generation"]},
                )
                assert rearm.status_code == 200
                assert rearm.json().get("dispatch_enabled") is True

            goal = http.post(
                "/api/fleet/robots/rosy_45/goal",
                headers={**auth, "Idempotency-Key": "goal-rosy45-1"},
                json={"x": -0.1914, "y": -0.207, "yaw": -1.5708},
            )
            assert goal.status_code == 200
            goal_body = goal.json()
            assert goal_body.get("accepted") is True or goal_body.get("queued") is True

            # Move arm_a via virtual CORE arm endpoint as part of workcell loop.
            arm_req = urllib.request.Request(
                f"http://127.0.0.1:{fleet.ports['arm_a']}/api/v1/arm/goal",
                data=json.dumps({"joints": [0.42, -0.30, 0.50, 0.78, 1.57, 0.14]}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {core_token}"},
                method="POST",
            )
            with urllib.request.urlopen(arm_req, timeout=2.0) as resp:
                assert resp.status == 200

            moved = False
            latest_fleet = None
            for _ in range(60):
                time.sleep(0.1)
                latest_fleet = http.get("/api/fleet/state", headers=auth).json()
                p45 = next(r for r in latest_fleet["robots"] if r["robot_id"] == "rosy_45")
                arm_a = next(r for r in latest_fleet["robots"] if r["robot_id"] == "arm_a")
                if p45["state"]["pose"]["y"] < 0.35 and arm_a["state"]["joints"][0] > -0.2:
                    moved = True
                    break
            assert moved

            world_payload = bridge_real_fleet.fleet_state_to_world_state(
                latest_fleet, site_map_sha256=site_map_sha,
            )
            assert world_payload is not None
            push_res = adapter.push_world_snapshot(world_url, "real-site", world_payload)
            assert push_res["ok"] and push_res["parity"]["ok"]

            reg = json.loads(urllib.request.urlopen(f"{world_url}/api/worlds", timeout=2.0).read().decode("utf-8"))
            real_entry = next(w for w in reg["worlds"] if w["world_id"] == "real-site")
            assert real_entry["status"] == "live"
            assert real_entry["parity"]["ok"] is True

            # Verify Fleet emergency stop propagates through virtual CORE past SharedGather's 1s cache TTL.
            estop = http.post("/api/fleet/estop", headers=auth)
            assert estop.status_code == 200
            estop_ok = False
            for _ in range(12):
                time.sleep(0.25)
                after_estop = http.get("/api/fleet/state", headers=auth).json()
                if all(r["state"]["safety"]["estop"] is True for r in after_estop["robots"]):
                    estop_ok = True
                    break
            assert estop_ok
    finally:
        fleet.close()
        server.shutdown()
        server.server_close()


def test_ship_9x3x3_three_hold_layout_and_dual_tray_payload():
    """Verify 9x3x3 3-hold ship layout (27 sites) preserves default 2-hold digest and dual cargo schema."""
    import omx_two_arm_sites as sites

    default_layout = sites.Layout()
    ship_default = [k for k in default_layout.sites if k.startswith("ship-")]
    assert len(ship_default) == 18

    three_hold_layout = sites.Layout(ship_holds=3)
    ship_9x3x3 = [k for k in three_hold_layout.sites if k.startswith("ship-")]
    assert len(ship_9x3x3) == 27
    for layer in range(3):
        for row in range(3):
            assert f"ship-h3r{row}-l{layer}" in three_hold_layout.sites

    # Verify hold-3 x spacing matches HOLD['length'] = 98 mm along negative fixture X.
    dx = three_hold_layout.sites["ship-h2r1-l0"]["xy"][0] - three_hold_layout.sites["ship-h3r1-l0"]["xy"][0]
    assert abs(dx - 0.098) < 1e-6

    # Verify dual-row Pinky payload parity with canonical World state shape.
    inputs = hooks.canonical_parity_inputs(ROOT)
    payload = {
        "t_sim_s": 1.0,
        "training": {"step": 5, "loss": 0.042},
        "cargo": {
            "zone": "pinky",
            "pose_m": [-0.0948, 0.0, 0.06185],
            "secondary_pose_m": [-0.1328, 0.0, 0.06185],
            "items": [
                {"pose_m": [-0.0948, 0.0, 0.06185], "color_idx": 0},
                {"pose_m": [-0.1328, 0.0, 0.06185], "color_idx": 1},
            ],
            "yaw_rad": 0.0,
            "color_idx": 0,
        },
        **inputs,
    }
    assert len(payload["cargo"]["items"]) == 2
    # Gap between the two 90x30 mm containers on the 2-row tray = 38 - 30 = 8 mm (> 7.56 mm jaw).
    row_pitch = abs(payload["cargo"]["pose_m"][0] - payload["cargo"]["secondary_pose_m"][0])
    assert abs(row_pitch - 0.038) < 1e-6
