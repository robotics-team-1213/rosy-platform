"""core.node — 중심 노드: 서비스 조립 + ROS 실행 + API 서버 스레드 (D-1)."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from core_common.identity import SOFTWARE_VERSION
from core.services import CoreServices

# Teardown bounds. The executor drain and the API join run one after the other, and the
# uvicorn graceful bound runs inside the join, so the worst case is 3 + 5 = 8 s — inside
# rosy-core.service TimeoutStopSec=15, whose SIGKILL is the backstop for anything that
# overruns these (a callback or a request handler that never returns).
EXECUTOR_DRAIN_TIMEOUT_S = 3.0
API_GRACEFUL_TIMEOUT_S = 3.0
API_JOIN_TIMEOUT_S = 5.0


def _resolve_path(config: dict[str, Any], key: str, fallback: Path) -> Path:
    raw = config.get("robot", {}).get(key) or config.get(key)
    if raw:
        candidate = Path(str(raw)).expanduser()
        if candidate.is_absolute():
            return candidate
        try:
            from ament_index_python.packages import get_package_share_directory
            return Path(get_package_share_directory("core")) / "config" / candidate.name
        except Exception:
            return candidate
    return fallback


class RosyCoreNode(Node):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__("core")
        self._config = config
        self._api_thread: Optional[threading.Thread] = None
        self._api_server = None

        from core_common.profile import RobotProfile
        import yaml

        profile_path = _resolve_path(config, "profile",
                                     Path(__file__).resolve().parent.parent / "config" / "profile.pinky_pro.yaml")
        capability_path = _resolve_path(config, "capabilities",
                                        Path(__file__).resolve().parent.parent / "config" / "capabilities.yaml")
        profile = RobotProfile.load(profile_path)
        capability_data = yaml.safe_load(capability_path.read_text(encoding="utf-8"))

        waypoints_path = Path.home() / ".rosy" / "waypoints.json"
        self.core = CoreServices.build(config, profile, capability_data, waypoints_path)

        from core.bridge.control_sensor_adapter import ControlSensorAdapter
        control_cfg = config.get("control", {}) or {}
        if not isinstance(control_cfg, dict):
            raise ValueError("control configuration must be a mapping")
        sensor_cfg = control_cfg.get("sensor_adapter", {}) or {}
        if isinstance(sensor_cfg, dict):
            # The release generation belongs to the mounted Device runtime,
            # not to a baked image. Fill it from Compose only when the
            # calibration block did not already pin one; the loader then
            # rejects a context/generation mismatch before creating a worker.
            sensor_cfg = dict(sensor_cfg)
            calibration_cfg = sensor_cfg.get("calibration")
            if isinstance(calibration_cfg, dict):
                calibration_cfg = dict(calibration_cfg)
                active_generation = os.environ.get("ROSY_DATA_GENERATION", "").strip()
                data_root = os.environ.get("ROSY_DATA_PATH", "").strip()
                if active_generation and not calibration_cfg.get("active_generation"):
                    calibration_cfg["active_generation"] = active_generation
                if data_root and not calibration_cfg.get("data_root"):
                    calibration_cfg["data_root"] = data_root
                sensor_cfg["calibration"] = calibration_cfg
        namespace = self.get_namespace() if callable(getattr(self, "get_namespace", None)) else None
        self.control_adapter = ControlSensorAdapter(sensor_cfg, namespace=namespace)
        self.core.control_adapter = self.control_adapter
        if self.control_adapter.enabled:
            self.control_adapter.bind_safety(self.core.safety)

        from core.system.ros_graph import RosGraphMonitor
        self.ros_graph_monitor = RosGraphMonitor(self)
        self.core.runtime_probe.attach_ros_graph_provider(
            self.ros_graph_monitor.snapshot
        )

        from core.bridge.ros_bridge import RosBridge
        self.bridge = RosBridge(self, self.core)

        self.get_logger().info(
            f"core up: robot_id={self.core.identity.robot_id} model={profile.model}")
        self._start_events()
        self.core.state.set_map_id(config.get("navigation", {}).get("map_id"))
        self.core.events.publish("system.boot", source="core",
                                 data={"version": SOFTWARE_VERSION})
        self._start_api()

    def _start_events(self) -> None:
        def _on_event(event) -> None:
            self.get_logger().debug("event %s seq=%d", event.type, event.seq)

        self.core.events.subscribe(_on_event)

    def _start_api(self) -> None:
        port = int(self._config.get("network", {}).get("api_port", 8080))
        host = str(self._config.get("network", {}).get("api_host", "0.0.0.0"))

        import uvicorn
        from core_api_web.api.app import create_app

        app = create_app(self._config, self.core)
        # timeout_graceful_shutdown: /ws/events, /ws/state 는 await 에 park 해 있어서
        # should_exit 만으로는 바로 끝나지 않는다. 대시보드가 붙은 채 정지하면 이 상한이
        # 없을 때 아래 API join 상한을 매번 다 쓴다.
        server_config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                                       timeout_graceful_shutdown=API_GRACEFUL_TIMEOUT_S)
        self._api_server = uvicorn.Server(server_config)
        self._api_thread = threading.Thread(target=self._api_server.run, daemon=True,
                                            name="rosy-api")
        self._api_thread.start()
        self.get_logger().info(f"api server on {host}:{port}")

    def run(self) -> None:
        executor = MultiThreadedExecutor()
        executor.add_node(self)
        try:
            self.control_adapter.attach(executor)
            executor.spin()
        finally:
            try:
                self.control_adapter.detach(executor)
                executor.remove_node(self)
            finally:
                if not _stop_executor(executor, EXECUTOR_DRAIN_TIMEOUT_S,
                                      self.get_logger()):
                    self.get_logger().warning(
                        "executor callbacks were not drained within "
                        f"{EXECUTOR_DRAIN_TIMEOUT_S:.1f}s (see the reason above); "
                        "continuing teardown — systemd TimeoutStopSec is the backstop")

    def shutdown(self) -> None:
        if self._api_server is not None:
            self._api_server.should_exit = True
        self.core.events.publish("system.shutdown", severity="warning", source="core")
        self.control_adapter.close()
        self.get_logger().info("core shutting down")
        if self._api_thread is not None:
            self._api_thread.join(API_JOIN_TIMEOUT_S)
            if self._api_thread.is_alive():
                self.get_logger().warning(
                    f"api thread still alive after {API_JOIN_TIMEOUT_S:.1f}s; "
                    "the API port is still held")


def _stop_executor(executor: Any, timeout_s: float, logger: Any = None) -> bool:
    """Stop the executor and wait (bounded) for callbacks already handed to its workers.

    When spin() returns, MultiThreadedExecutor worker threads may still be running timer
    callbacks, and more may be queued. Left alone they run after main() has taken the rclpy
    context down and while the interpreter finalizes ("Failed to publish: publisher's
    context is invalid", then one SIGSEGV at exit in 105 WSL runs, 2026-09-22).
    rclpy 7.1.x (Jazzy) does not drain the pool itself: Executor.shutdown() never waits
    for in-flight work, and MultiThreadedExecutor does not shut its ThreadPoolExecutor
    down. So cancel the queued callbacks and join the running ones here.
    Drain first, then shut the executor down: Executor.shutdown() destroys the guard
    condition that a running callback triggers when it finishes ("cannot use Destroyable
    because destruction was requested").
    Returns False when the bound expired with callbacks still running, or when this
    executor has no ThreadPoolExecutor to drain — an rclpy that renames or drops it
    would otherwise take the guarantee away in silence (the ROS-lane canary
    `test_core_node_teardown_ros.py` pins the attribute).
    Nothing here can stop a callback that never returns: the pool's workers are
    non-daemon and the interpreter joins them without a bound at exit, so the real
    backstop is the SIGKILL systemd sends at TimeoutStopSec.
    """
    drained = True
    pool = getattr(executor, "_executor", None)
    if isinstance(pool, ThreadPoolExecutor):
        drain = threading.Thread(target=pool.shutdown,
                                 kwargs={"wait": True, "cancel_futures": True},
                                 daemon=True, name="rosy-executor-drain")
        drain.start()
        drain.join(timeout_s)
        drained = not drain.is_alive()
        if not drained and logger is not None:
            logger.warning(
                f"executor worker pool still running callbacks after {timeout_s:.1f}s")
    else:
        drained = False
        if logger is not None:
            logger.warning(
                f"{type(executor).__name__} exposes no ThreadPoolExecutor to drain "
                f"(_executor={type(pool).__name__}); in-flight callbacks may outlive "
                "the context teardown in main()")
    try:
        executor.shutdown(timeout_sec=0)
    except Exception as exc:
        if logger is not None:
            logger.warning(f"executor shutdown raised during teardown: {exc!r}")
    return drained
