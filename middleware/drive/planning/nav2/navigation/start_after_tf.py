#!/usr/bin/env python3
"""Start the Nav2 navigation manager once the costmap transforms exist."""

from pathlib import Path
import sys

import yaml


def costmap_frames(params_path, namespace):
    params = yaml.safe_load(Path(params_path).read_text(encoding="utf-8"))
    frames = []
    for name in ("global_costmap", "local_costmap"):
        if namespace == "/":
            config = params.get(name, {}).get(name, {})
        else:
            config = params.get(f"{namespace}/{name}", {}).get(name, {})
        values = config.get("ros__parameters", {})
        frames.append((values.get("global_frame", "map"), values.get("robot_base_frame", "base_link")))
    return frames


def request_startup(buffer, client, request, frames, latest):
    if client.service_is_ready() and all(
        buffer.can_transform(target, base, latest) for target, base in frames
    ):
        return client.call_async(request)
    return None


def main():
    import rclpy
    from nav2_msgs.srv import ManageLifecycleNodes
    from rclpy.executors import ExternalShutdownException
    from rclpy.time import Time
    from tf2_ros import Buffer, TransformListener

    rclpy.init()
    node = rclpy.create_node("nav2_start_after_tf")
    try:
        frames = costmap_frames(sys.argv[1], node.get_namespace())
        buffer = Buffer(node=node)
        listener = TransformListener(buffer, node)
        client = node.create_client(ManageLifecycleNodes, "lifecycle_manager_navigation/manage_nodes")
        request = ManageLifecycleNodes.Request(command=ManageLifecycleNodes.Request.STARTUP)
        latest = Time()
        node.get_logger().info(f"Waiting for Nav2 costmap transforms: {frames}")
        while rclpy.ok():
            result = request_startup(buffer, client, request, frames, latest)
            if result is not None:
                rclpy.spin_until_future_complete(node, result, timeout_sec=120.0)
                if not rclpy.ok():
                    return 0
                if not result.done() or not result.result().success:
                    node.get_logger().error("Nav2 lifecycle manager did not complete STARTUP")
                    return 1
                return 0
            rclpy.spin_once(node, timeout_sec=0.5)
    except (ExternalShutdownException, KeyboardInterrupt):
        return 0
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
