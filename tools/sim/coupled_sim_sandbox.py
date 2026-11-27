#!/usr/bin/env python3
"""Live 4-layer coupled simulation sandbox (D-1088 Vertical Slice 2).

Wires together without editing operational Fleet/CORE/World logic:
  1. FaultedVirtualCoreFleet (boundary fault injection around VirtualCoreFleet)
  2. CoupledSimController (single cargo ledger SSOT, 3 boundary events, faults HTTP)
  3. Isolated Sim-Fleet FastAPI app (real operations/fleet dispatcher + console)
  4. Read-Only ROSY World server (applications/world/serve.py SSE + parity checks)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

SIM_DIR = Path(__file__).resolve().parent
REPO = SIM_DIR.parents[1] if len(SIM_DIR.parents) > 1 and (SIM_DIR.parents[1] / "middleware").is_dir() else SIM_DIR


def _ensure_repo_paths() -> None:
    entries = (
        REPO / "applications" / "world",
        REPO / "tools" / "sim",
        REPO / "operations" / "fleet",
        REPO / "operations" / "account",
        REPO / "operations" / "decision" / "src",
        REPO / "operations" / "world" / "src",
        REPO / "operations" / "site_execution" / "src",
        REPO / "contracts" / "foundation",
        REPO / "contracts" / "learning" / "src",
        REPO / "contracts" / "skill" / "src",
        REPO / "contracts" / "motion" / "src",
        REPO / "middleware" / "core" / "services",
        REPO / "operations" / "processes" / "palletizing" / "src",
        REPO / "applications" / "fleet" / "gateway" / "src",
    )
    for entry in entries:
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)


_ensure_repo_paths()

import coupled_sim_controller as csc  # noqa: E402
import serve as world_serve  # noqa: E402
import virtual_core_fleet as vcore  # noqa: E402
from world_env_adapter import WorldPublisher  # noqa: E402


class FaultedVirtualRobotState(vcore.VirtualRobotState):
    """Virtual CORE robot runtime gated at the physical/bridge boundary by FaultRegistry."""

    def __init__(self, robot_id: str, faults: csc.FaultRegistry) -> None:
        super().__init__(robot_id)
        self.faults = faults

    def step(self, dt: float) -> None:
        if self.is_arm:
            if not self.faults.apply_arm_presence_boundary(self.robot_id, True):
                return
            super().step(dt)
            return
        if self.faults.apply_pinky_motion_boundary(self.robot_id, 1.0, 1.0) == (0.0, 0.0):
            with self.lock:
                self.velocity = {"linear": 0.0, "angular": 0.0}
            return
        super().step(dt)


class FaultedVirtualCoreFleet(vcore.VirtualCoreFleet):
    """6-robot VirtualCoreFleet whose physics step honours boundary FaultRegistry toggles."""

    def __init__(self, *, faults: csc.FaultRegistry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.faults = faults
        self.robots = {rid: FaultedVirtualRobotState(rid, faults) for rid in vcore.DEFAULT_ROBOT_ORDER}


class CoupledSimSandbox:
    """Isolated 4-layer coupled sim sandbox (Virtual CORE <-> Sim-Fleet <-> Controller <-> World)."""

    def __init__(
        self,
        *,
        work_dir: Path,
        world_bundle_dir: Path,
        site_map_sha256: str,
        world_id: str = "coupled-sim",
        adapter: str = "gazebo",
        robot_id: str = "rosy_45",
        world_port: int = 0,
        sim_port: int = 0,
        core_token: str = "coupled-sim-core-token",
        operator_token: str = "coupled-sim-op-token",
    ) -> None:
        self.work_dir = Path(work_dir)
        self.world_bundle_dir = Path(world_bundle_dir)
        self.site_map_sha256 = site_map_sha256
        self.world_id = world_id
        self.adapter = adapter
        self.robot_id = robot_id
        self.world_port = int(world_port)
        self.sim_port = int(sim_port)
        self.core_token = core_token
        self.operator_token = operator_token
        self.auth_headers = {"Authorization": f"Bearer {operator_token}"}

        self.world_server: Any = None
        self.world_thread: threading.Thread | None = None
        self.world_url: str = ""
        self.controller: csc.CoupledSimController | None = None
        self.sim_server: Any = None
        self.sim_thread: threading.Thread | None = None
        self.sim_url: str = ""
        self.virtual_fleet: FaultedVirtualCoreFleet | None = None
        self.app: Any = None
        self._closed = False

    def __enter__(self) -> "CoupledSimSandbox":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        from fleet._source_layout import bootstrap_sources

        bootstrap_sources()
        from fleet.server.app import create_app
        from fleet.server.console import FleetConsole
        from fleet.server.task_service import FleetTaskService
        from fleet.server.task_store import FleetTaskStore
        from fleet.swarm.robots import load_robots
        from fleet.swarm.transport import HttpRobotClient
        from rosy_account.site_users import load_site_accounts

        self.work_dir.mkdir(parents=True, exist_ok=True)
        worlds_dir = self.work_dir / "worlds"
        worlds_dir.mkdir(parents=True, exist_ok=True)

        # Layer 4: Read-Only ROSY World
        self.world_server = world_serve.make_server(
            self.world_bundle_dir, "127.0.0.1", self.world_port, worlds_dir=worlds_dir,
        )
        self.world_thread = threading.Thread(target=self.world_server.serve_forever, daemon=True, name="sim-world")
        self.world_thread.start()
        self.world_url = f"http://127.0.0.1:{self.world_server.server_port}"

        # Layer 2: Coupled Scenario & Fault Controller
        publisher = WorldPublisher(
            world_id=self.world_id, world_url=self.world_url, worlds_dir=worlds_dir, best_effort=False,
        )
        self.controller = csc.CoupledSimController(
            world_id=self.world_id,
            adapter=self.adapter,
            site_map_sha256=self.site_map_sha256,
            robot_id=self.robot_id,
            world_publisher=publisher,
        )
        self.sim_server = csc.build_server(self.controller, host="127.0.0.1", port=self.sim_port)
        self.sim_thread = threading.Thread(target=self.sim_server.serve_forever, daemon=True, name="sim-controller")
        self.sim_thread.start()
        self.sim_url = f"http://127.0.0.1:{self.sim_server.server_port}"

        # Layer 1: Boundary-Faulted 6-Robot Virtual CORE
        self.virtual_fleet = FaultedVirtualCoreFleet(
            faults=self.controller.faults, host="127.0.0.1", base_port=0, token=self.core_token,
        )
        self.virtual_fleet.start()

        # Layer 3: Isolated Sim-Fleet FastAPI App
        robots_yaml = self.work_dir / "robots.yaml"
        self.virtual_fleet.write_robots_yaml(robots_yaml)
        endpoints = load_robots(robots_yaml)
        clients = [HttpRobotClient(ep) for ep in endpoints]
        console = FleetConsole(endpoints, clients)
        tasks = FleetTaskService(FleetTaskStore(self.work_dir / "fleet.sqlite3"), robot_ids=console.robot_ids)

        users_yaml = self.work_dir / "site-users.yaml"
        users_yaml.write_text(
            "users:\n"
            "  - principal_id: sim-operator\n"
            "    role: operator\n"
            f"    token_sha256: {hashlib.sha256(self.operator_token.encode()).hexdigest()}\n",
            encoding="utf-8",
        )
        site_users, site_logins = load_site_accounts(users_yaml)
        self.app = create_app(
            console,
            task_service=tasks,
            site_users=site_users,
            site_logins=site_logins,
            start_task_dispatcher=True,
        )
        publisher.publish(self.controller.build_world_state())

    def _http_json(self, base_url: str, method: str, path: str, body: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(base_url + path, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {err.code} {method} {path}: {raw}") from err

    def set_fault(self, fault_id: str, enabled: bool = True, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Toggle a boundary fault on Layer 2 CoupledSimController over HTTP."""
        payload: dict[str, Any] = {"enabled": enabled}
        if params is not None:
            payload["params"] = params
        return self._http_json(self.sim_url, "POST", f"/api/sim/faults/{fault_id}", payload)

    def dispatch_pinky_goal(self, client: Any, x: float, y: float, yaw: float, idempotency_key: str) -> dict[str, Any]:
        """Arm Fleet dispatch if needed and issue a real Fleet goal for ``self.robot_id``."""
        ctrl = client.get("/api/fleet/dispatch-control", headers=self.auth_headers)
        ctrl.raise_for_status()
        if not ctrl.json().get("dispatch_enabled"):
            rearm = client.post(
                "/api/fleet/dispatch/rearm",
                headers=self.auth_headers,
                json={"expected_generation": ctrl.json()["generation"]},
            )
            rearm.raise_for_status()
        res = client.post(
            f"/api/fleet/robots/{self.robot_id}/goal",
            headers={**self.auth_headers, "Idempotency-Key": idempotency_key},
            json={"x": x, "y": y, "yaw": yaw},
        )
        res.raise_for_status()
        return res.json()

    def _move_virtual_arm(self, arm_id: str, joints: list[float]) -> None:
        if self.virtual_fleet is None:
            raise RuntimeError("sandbox not started")
        port = self.virtual_fleet.ports[arm_id]
        self._http_json(
            f"http://127.0.0.1:{port}", "POST", "/api/v1/arm/goal", {"joints": list(joints)},
            headers={"Authorization": f"Bearer {self.core_token}"},
        )

    def trigger_s3_handoff(
        self, *, dx_m: float, dy_m: float, dyaw_rad: float, bed_velocity_measured: bool = True, rtf: float = 1.0,
    ) -> dict[str, Any]:
        """Send S3_ARRIVED_SETTLED to Layer 2 and move virtual arm_s toward pick when admitted."""
        res = self._http_json(self.sim_url, "POST", "/api/sim/events/s3-arrived", {
            "robot_id": self.robot_id,
            "dx_m": dx_m,
            "dy_m": dy_m,
            "dyaw_rad": dyaw_rad,
            "bed_velocity_measured": bed_velocity_measured,
            "rtf": rtf,
        })
        if res.get("accepted"):
            self._move_virtual_arm("arm_s", vcore.ARM_PRESETS["pick"])
        return res

    def complete_arm_s_lift_and_clear(
        self, *, lifted: bool = True, bilateral_lift: bool = True, rtf: float = 1.0,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Execute Event 2 (lift/drop) and Event 3 (arm_s home + clearance)."""
        lift_res = self._http_json(self.sim_url, "POST", "/api/sim/events/cargo-lifted", {
            "arm_id": "arm_s", "lifted": lifted, "bilateral_lift": bilateral_lift, "rtf": rtf,
        })
        if not lift_res.get("accepted"):
            return lift_res, None
        self._move_virtual_arm("arm_s", vcore.ARM_PRESETS["home"])
        clear_res = self._http_json(self.sim_url, "POST", "/api/sim/events/cell-bed-clear", {
            "arm_id": "arm_s", "arm_in_bed_zone": False, "rtf": rtf,
        })
        return lift_res, clear_res

    def advance_downstream_ab(self, *, rtf: float = 1.0) -> dict[str, Any]:
        """Advance ON_BELT -> IN_CELL_AB -> ON_SHIP and drive virtual arm_a/arm_b joints."""
        if self.controller is None:
            raise RuntimeError("sandbox not started")
        belt = self.controller.advance_cell_stage("ON_BELT", rtf=rtf)
        if not belt.get("accepted"):
            return belt
        self._move_virtual_arm("arm_a", vcore.ARM_PRESETS["pick"])
        in_ab = self.controller.advance_cell_stage("IN_CELL_AB", rtf=rtf)
        if not in_ab.get("accepted"):
            return in_ab
        self._move_virtual_arm("arm_b", vcore.ARM_PRESETS["place"])
        return self.controller.advance_cell_stage("ON_SHIP", rtf=rtf)

    def sample_vision_observation(self, raw_obs: dict[str, Any]) -> dict[str, Any]:
        """Route a synthetic overhead observation through the boundary FaultRegistry."""
        if self.controller is None:
            raise RuntimeError("sandbox not started")
        return self.controller.faults.apply_vision_boundary(raw_obs)

    def sync_world(self, fleet_state: dict[str, Any]) -> dict[str, Any]:
        """Merge live Sim-Fleet kinematics into Read-Only World projection and publish."""
        if self.controller is None or self.controller.world_publisher is None:
            raise RuntimeError("sandbox not started")
        snap = self.controller.build_world_state()
        by_id = {row["robot_id"]: row.get("state") or {} for row in fleet_state.get("robots", [])}
        for item in snap["pinkys"]:
            st = by_id.get(item["id"]) or {}
            pose = st.get("pose")
            if isinstance(pose, dict):
                item["pose_m"] = [float(pose["x"]), float(pose["y"]), 0.0]
                item["yaw_rad"] = float(pose["yaw"])
                if item["id"] == self.robot_id:
                    snap["pinky"]["pose_m"] = list(item["pose_m"])
                    snap["pinky"]["yaw_rad"] = item["yaw_rad"]
        for arm_id in ("arm_s", "arm_a", "arm_b"):
            joints = (by_id.get(arm_id) or {}).get("joints")
            if isinstance(joints, list) and len(joints) == 6:
                snap["arms"][arm_id] = [float(q) for q in joints]
        self.controller.world_publisher.publish(snap)
        return snap

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.virtual_fleet is not None:
            self.virtual_fleet.close()
        for srv in (self.sim_server, self.world_server):
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except OSError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="World bundle directory")
    parser.add_argument("--work-dir", type=Path, required=True, help="Isolated runtime scratch directory")
    parser.add_argument("--site-map-sha256", required=True)
    parser.add_argument("--world-port", type=int, default=8140)
    parser.add_argument("--sim-port", type=int, default=8190)
    parser.add_argument("--fleet-port", type=int, default=8091)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)

    with CoupledSimSandbox(
        work_dir=args.work_dir,
        world_bundle_dir=args.bundle,
        site_map_sha256=args.site_map_sha256,
        world_port=0 if args.self_check else args.world_port,
        sim_port=0 if args.self_check else args.sim_port,
    ) as sandbox:
        if args.self_check:
            from fastapi.testclient import TestClient

            with TestClient(sandbox.app) as client:
                st = client.get("/api/fleet/state", headers=sandbox.auth_headers).json()
                snap = sandbox.sync_world(st)
                print(json.dumps({"online": st["fleet"]["online"], "world_id": snap["world_id"], "read_only": snap["read_only"]}))
            return 0
        import uvicorn

        uvicorn.run(sandbox.app, host="127.0.0.1", port=args.fleet_port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
