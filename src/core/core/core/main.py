"""core.main — 진입점: ROS 노드 기동 + API 서버 (P1-1, ADR-D-1).

프로세스 구조:
- Main Thread: rclpy 노드 "core" (MultiThreadedExecutor)
- Worker Thread: uvicorn + FastAPI
"""

from __future__ import annotations


def main() -> None:
    import os

    from core_common.rmw import apply_cyclone_rmw

    apply_cyclone_rmw(os.environ)

    import rclpy

    from core_common.config import load_config
    from core.node import RosyCoreNode

    rclpy.init()
    node = None
    try:
        config = load_config()
        node = RosyCoreNode(config)
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            try:
                node.shutdown()
            except Exception:
                pass
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
