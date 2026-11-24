#!/usr/bin/env python3
"""Start the Nav2 navigation manager once the costmap transforms exist."""

from pathlib import Path
import os
import sys
import time

import yaml

MAX_STARTUP_ATTEMPTS = 3
STARTUP_RETRY_S = 5.0
WAIT_LOG_INTERVAL_S = 10.0


def costmap_frames(params_path, namespace):
    params = yaml.safe_load(Path(params_path).read_text(encoding="utf-8"))
    frames = []
    for name in ("global_costmap", "local_costmap"):
        group = f"{namespace.rstrip('/')}/{name}"
        nested = params.get(group, params.get(group.lstrip("/"), {})).get(name, {})
        flat = f"{group}/{name}"
        config = params.get(flat, params.get(flat.lstrip("/"), nested))
        values = config.get("ros__parameters", {})
        frames.append((values.get("global_frame", "map"), values.get("robot_base_frame", "base_link")))
    return frames


def request_startup(buffer, client, request, frames, latest):
    if client.service_is_ready() and all(
        buffer.can_transform(target, base, latest) for target, base in frames
    ):
        return client.call_async(request)
    return None


def missing_requirements(buffer, client, frames, latest):
    missing = []
    if not client.service_is_ready():
        missing.append("lifecycle_manager")
    for target, base in frames:
        if not buffer.can_transform(target, base, latest):
            missing.append(f"{target}->{base}")
    return missing


def run_startup_loop(
    node,
    buffer,
    client,
    request,
    frames,
    latest,
    *,
    spin_once,
    spin_until_future_complete,
    ok,
    sleep=time.sleep,
    monotonic=time.monotonic,
    max_attempts=MAX_STARTUP_ATTEMPTS,
    retry_s=STARTUP_RETRY_S,
    log_interval_s=WAIT_LOG_INTERVAL_S,
    check_interval_s=0.5,
):
    last_log = monotonic() - log_interval_s
    next_check = monotonic()
    attempts = 0
    while ok():
        now = monotonic()
        if now < next_check:
            spin_once(node, timeout_sec=max(0.01, min(check_interval_s, next_check - now)))
            # Keep progressing if a test injects a non-advancing fake clock.
            if monotonic() <= now:
                next_check = now
            continue
        result = request_startup(buffer, client, request, frames, latest)
        if result is None:
            now = monotonic()
            if now - last_log >= log_interval_s:
                missing = missing_requirements(buffer, client, frames, latest)
                node.get_logger().info(f"Still waiting for Nav2 startup prerequisites: {missing}")
                last_log = now
            next_check = now + check_interval_s
            spin_once(node, timeout_sec=check_interval_s)
            continue
        spin_until_future_complete(node, result, timeout_sec=120.0)
        if not ok():
            return 0
        try:
            response = result.result() if result.done() else None
        except Exception:
            response = None
        if response is not None and response.success:
            return 0
        attempts += 1
        node.get_logger().error(
            f"Nav2 lifecycle manager STARTUP attempt {attempts}/{max_attempts} failed"
        )
        if attempts >= max_attempts:
            return 1
        sleep(retry_s)
        next_check = monotonic()
    return 0


def _make_executor():
    from rclpy.executors import SingleThreadedExecutor

    if os.environ.get("ROSY_EXECUTOR", "events").strip().lower() == "single":
        return SingleThreadedExecutor()
    try:
        from rclpy.experimental.events_executor import EventsExecutor
        return EventsExecutor()
    except ImportError:
        return SingleThreadedExecutor()


def main():
    import rclpy
    from nav2_msgs.srv import ManageLifecycleNodes
    from rclpy.executors import ExternalShutdownException
    from rclpy.time import Time
    from tf2_ros import Buffer, TransformListener

    rclpy.init()
    node = rclpy.create_node("nav2_start_after_tf")
    executor = _make_executor()
    executor.add_node(node)
    try:
        frames = costmap_frames(sys.argv[1], node.get_namespace())
        buffer = Buffer(node=node)
        listener = TransformListener(buffer, node)
        client = node.create_client(ManageLifecycleNodes, "lifecycle_manager_navigation/manage_nodes")
        request = ManageLifecycleNodes.Request(command=ManageLifecycleNodes.Request.STARTUP)
        latest = Time()
        node.get_logger().info(f"Waiting for Nav2 costmap transforms: {frames}")
        return run_startup_loop(
            node, buffer, client, request, frames, latest,
            spin_once=lambda _node, timeout_sec=0.5: executor.spin_once(timeout_sec=timeout_sec),
            spin_until_future_complete=(
                lambda _node, future, timeout_sec=120.0:
                    executor.spin_until_future_complete(future, timeout_sec=timeout_sec)
            ),
            ok=rclpy.ok,
        )
    except (ExternalShutdownException, KeyboardInterrupt):
        return 0
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
