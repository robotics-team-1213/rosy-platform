"""Unit tests for Rosy World 7-stage factory timeline compiler, bundle packing, and SSE stream."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications" / "world"))
sys.path.insert(0, str(ROOT / "tools" / "sim"))

import build_bundle  # noqa: E402
import serve  # noqa: E402
from factory_flow_receipts import STAGES  # noqa: E402
from world_factory_timeline import compile_timeline  # noqa: E402


def _make_closed_fixture(base: Path) -> tuple[Path, Path, Path]:
    closed = base / "closed"
    ev_dir = closed / "ev"
    ev_dir.mkdir(parents=True)
    site_hash = "ab" * 32

    site_map = {
        "version": 368,
        "map": {
            "schema": "rosy.site_map/1",
            "map_id": "world_261026",
            "places": [
                {"id": "C1", "x": -0.414, "y": 0.47},
                {"id": "C2", "x": -0.1914, "y": 0.47},
                {"id": "C3", "x": 0.032, "y": 0.47},
                {"id": "S3", "x": 0.745, "y": -0.207, "precision_stop": {
                    "yaw_rad": 3.141592, "longitudinal_m": 0.04, "lateral_m": 0.025,
                    "heading_rad": 0.12, "position_uncertainty_m": 0.005,
                    "heading_uncertainty_rad": 0.02, "max_correction_m": 0.04,
                }},
            ],
            "edges": [
                {"id": "bay_2", "from": "P2", "to": "C2", "polyline": [[-0.19, 0.04], [-0.1914, 0.47]]},
                {"id": "bay_3", "from": "P3", "to": "C3", "polyline": [[0.03, 0.04], [0.032, 0.47]]},
                {"id": "bar_32", "from": "P3", "to": "P2", "polyline": [[0.03, 0.04], [-0.19, 0.04]]},
                {"id": "bar_21", "from": "P2", "to": "P1", "polyline": [[-0.19, 0.04], [-0.41, 0.04]]},
                {"id": "park_out", "from": "P2", "to": "S1", "polyline": [[-0.19, 0.04], [-0.67, -0.135]]},
                {"id": "park_gate_out", "from": "S1", "to": "S2", "polyline": [[-0.67, -0.135], [-0.67, -0.24]]},
                {"id": "loop_left", "from": "S2", "to": "S4", "polyline": [[-0.67, -0.24], [0.0, -0.24]]},
                {"id": "loop_right", "from": "S1", "to": "S3", "polyline": [[-0.67, -0.135], [0.745, -0.207]]},
                {"id": "upper_east", "from": "S3", "to": "U1", "polyline": [[0.745, -0.207], [0.627, -0.246]]},
                {"id": "upper_west", "from": "U1", "to": "C2", "polyline": [[0.627, -0.246], [-0.1914, 0.47]]},
            ],
        },
    }
    site_map_path = base / "site-map.json"
    site_map_path.write_text(json.dumps(site_map), encoding="utf-8")

    reg_path = base / "site-registration.json"
    reg_path.write_text(json.dumps({
        "site_from_cell": {"yaw_rad": -1.5707963, "translation_m": [0.793, 0.355, 0.0]}
    }), encoding="utf-8")

    payloads = {
        "c2_departure": {"edges": ["bay_2", "park_out"]},
        "s1_yield": {"denied": False, "route_edges": ["loop_right"]},
        "s3_stop": {"samples": [{"sim_time_s": 100.0, "pose_xy_yaw": [0.75, -0.20, -3.08]}]},
        "cell_claim": {"cell_id": "cell_s"},
        "arm_s_to_belt": {
            "fixture": {"tray": {"center": [0.07, 0.1]}, "belt": {"center": [0.15, 0.0]}},
            "samples": [
                {"phase": "approach", "box_position": [0.07, 0.1, 0.055]},
                {"phase": "carry", "box_position": [0.11, 0.05, 0.12]},
                {"phase": "place", "box_position": [0.15, 0.0, 0.059]},
            ],
        },
        "belt_transit": {
            "stdout": "SITE_NATIVE " + json.dumps({
                "stage": "belt_transit", "passed": True,
                "trace": [
                    {"time_s": 0.1, "xyz_m": [0.35, -0.003, 0.0332]},
                    {"time_s": 5.0, "xyz_m": [0.205, -0.003, 0.0332]},
                ],
            }),
        },
        "ab_stack": {
            "rows": [
                {"step": f"s{i + 1}", "container": f"bar-{i + 1}", "arm": "arm_b" if i % 2 else "arm_a",
                 "target": f"ship-h1r{i % 3}-l{i // 3}", "result": "pass"}
                for i in range(9)
            ],
        },
    }

    receipts = []
    for stage in STAGES:
        rel = f"ev/{stage}-0.json"
        raw = json.dumps(payloads[stage]).encode("utf-8")
        (closed / rel).write_bytes(raw)
        receipts.append({
            "schema": "rosy.factory-flow.receipt.v1",
            "run_id": "sim-test-001", "task_id": "task-test-001",
            "robot_id": "rosy_01", "cargo_id": "cargo-001",
            "site_map_sha256": site_hash,
            "stage": stage, "status": "pass",
            "evidence": [{"path": rel, "sha256": hashlib.sha256(raw).hexdigest()}],
        })
    (closed / "receipts.json").write_text(json.dumps(receipts), encoding="utf-8")
    return closed, site_map_path, reg_path


def test_compile_timeline_emits_verified_7_stages_and_rejects_tamper(tmp_path: Path) -> None:
    closed, site_map, reg = _make_closed_fixture(tmp_path)
    timeline = compile_timeline(closed, site_map, reg)

    assert timeline["schema"] == "rosy.world.factory-timeline.v1"
    assert timeline["arm_bases_site"]["arm_a"]["pose_m"] == [0.62625, 0.278, 0.084]
    assert timeline["arm_bases_site"]["arm_b"]["pose_m"] == [0.96275, 0.278, 0.084]
    assert [s["id"] for s in timeline["stages"]] == list(STAGES)
    assert [s["simulator"] for s in timeline["stages"]] == [
        "gazebo", "gazebo", "gazebo", "gazebo", "isaac", "isaac", "mujoco"
    ]
    assert timeline["fleet_robots"] == {
        "pinkys": ["rosy_42", "rosy_45", "rosy_46"],
        "arms": ["arm_s", "arm_a", "arm_b"],
    }
    times = [kf["time_s"] for kf in timeline["keyframes"]]
    assert times == sorted(times) and times[-1] == timeline["duration_s"]
    assert len(timeline["keyframes"][-1]["cell_ab"]["stacked"]) == 9
    assert all({"arm_s", "arm_a", "arm_b"} == set(kf["arms"]) for kf in timeline["keyframes"])
    assert all([p["id"] for p in kf["pinkys"]] == ["rosy_42", "rosy_45", "rosy_46"] for kf in timeline["keyframes"])

    # Extended mode emits 9 stages including A<->B temp-slot sorting and outbound dock dispatch.
    ext = compile_timeline(closed, site_map, reg, include_extended=True)
    assert [s["id"] for s in ext["stages"]] == list(STAGES) + ["ab_rehandle", "outbound_dispatch"]
    assert any(kf["stage"] == "ab_rehandle" and any(s["target"].startswith("tmp-") for s in kf["cell_ab"]["stacked"]) for kf in ext["keyframes"])
    assert any(kf["stage"] == "outbound_dispatch" and kf["cargo"]["zone"] == "pinky46_tray" for kf in ext["keyframes"])
    assert len(build_bundle.validate_factory_timeline(json.dumps(ext).encode("utf-8"))["stages"]) == 9

    # Fail closed if a receipt stage is marked failed.
    receipts = json.loads((closed / "receipts.json").read_text(encoding="utf-8"))
    receipts[2]["status"] = "fail"
    (closed / "receipts.json").write_text(json.dumps(receipts), encoding="utf-8")
    with pytest.raises(ValueError, match="unverified closed run"):
        compile_timeline(closed, site_map, reg)


def test_validate_factory_timeline_and_sse_stream(tmp_path: Path) -> None:
    closed, site_map, reg = _make_closed_fixture(tmp_path)
    timeline = compile_timeline(closed, site_map, reg)
    raw = json.dumps(timeline).encode("utf-8")
    assert build_bundle.validate_factory_timeline(raw)["run_id"] == "sim-test-001"

    bad = dict(timeline, duration_s=-1.0)
    with pytest.raises(ValueError, match="duration_s"):
        build_bundle.validate_factory_timeline(json.dumps(bad).encode("utf-8"))

    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "data").mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle_dir / "app.js").write_text("", encoding="utf-8")
    (bundle_dir / "studio-look.js").write_text("", encoding="utf-8")
    (bundle_dir / "SHA256SUMS.txt").write_text("", encoding="utf-8")
    (bundle_dir / "manifest.json").write_text(json.dumps({"inputs": {}}), encoding="utf-8")
    (bundle_dir / "data" / "factory-timeline.json").write_bytes(raw)

    server = serve.make_server(bundle_dir, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/sim/stream?mode=timeline&speed=2&hz=30&max_events=3"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("text/event-stream")
            assert resp.headers["Cache-Control"] == "no-store"
            body = resp.read().decode("utf-8")
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
        assert len(events) == 3
        assert all(e["schema"] == "rosy.world.factory-state.v1" and e["stream_mode"] == "verified_replay" for e in events)
        assert {"arm_s", "arm_a", "arm_b"} == set(events[0]["arms"]) and len(events[0]["pinkys"]) == 3
        assert events[-1]["sim_time_s"] >= events[0]["sim_time_s"]

        # Fresh factory-live.json takes priority over timeline in auto mode.
        live_payload = dict(events[0], stream_mode="verified_replay", observed_at_ms=time.time_ns() // 1_000_000, phase="live_override")
        (bundle_dir / "data" / "factory-live.json").write_text(json.dumps(live_payload), encoding="utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/sim/stream?mode=auto&max_events=1", timeout=5) as resp:
            auto_live = [json.loads(line[6:]) for line in resp.read().decode("utf-8").splitlines() if line.startswith("data: ")]
        assert auto_live[0]["stream_mode"] == "live" and auto_live[0]["phase"] == "live_override"

        # Stale factory-live.json falls back cleanly to verified_replay.
        live_payload["observed_at_ms"] -= 10_000
        (bundle_dir / "data" / "factory-live.json").write_text(json.dumps(live_payload), encoding="utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/sim/stream?mode=auto&max_events=1", timeout=5) as resp:
            auto_fallback = [json.loads(line[6:]) for line in resp.read().decode("utf-8").splitlines() if line.startswith("data: ")]
        assert auto_fallback[0]["stream_mode"] == "verified_replay"

        # Static shell/app assets send Cache-Control: no-store so desktop app picks up updates immediately.
        for asset in ("/", "/app.js", "/studio-look.js"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{asset}", timeout=5) as resp:
                assert resp.status == 200
                assert resp.headers["Cache-Control"] == "no-store"
    finally:
        server.stop_event.set()
        server.shutdown()
        server.server_close()


def test_standalone_app_manifest_and_mime() -> None:
    assert "manifest.webmanifest" in build_bundle.WEB_FILES
    assert "studio-look.js" in build_bundle.WEB_FILES
    assert "world-monitor.js" in build_bundle.WEB_FILES
    assert "omx-arm.js" in build_bundle.WEB_FILES
    manifest = json.loads((ROOT / "applications/world/web/manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/?view=factory"
    assert serve.WorldHandler.extensions_map[".webmanifest"] == "application/manifest+json"
    assert (ROOT / "applications/world/open-app.ps1").is_file()
