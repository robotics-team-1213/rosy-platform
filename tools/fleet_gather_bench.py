"""D-131 3단계 — 폴링 gather 의 규모 벤치.

가짜 로봇 N대에 대해 FleetConsole.snapshot() 이 N 개의 REST 폴링(D-81)을 얼마나
버티는지 측정한다. 숫자는 logs.md 에 기록되고, 그것이 N 상한 논의의 인용 원천이
된다. 측정 전에 규모를 주장하지 않는다(D-79·D-91).

사용:
    python tools/fleet_gather_bench.py --robots 20 --requests 40

표준 라이브러리 + fleet 패키지. ROS 없음.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
for name in ("site/fleet", "contracts/foundation", "runtime/events", "runtime/features"):
    path = SRC / name
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fleet.server.console import FleetConsole  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from fleet.swarm.transport import HttpRobotClient  # noqa: E402

STATE = {
    "robot_id": "rosy_00", "mode": "NAVIGATION", "navigation": "IDLE",
    "pose": {"x": 1.0, "y": 1.0, "yaw": 0.0},
    "battery": {"percent": 90, "voltage": 7.4}, "safety": {"estop": False},
    "seq": 1,
}


class FakeRobot(BaseHTTPRequestHandler):
    """GET /api/v1/robot/state 만 답하는 최소 로봇 스텁. 나머지는 404 다."""

    def do_GET(self):  # noqa: N802 — http.server 규약
        if self.path == "/api/v1/robot/state":
            body = json.dumps(STATE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):  # 벤치 출력을 조용히
        pass


def measure(n_robots: int, requests: int) -> dict:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRobot)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    endpoints = [RobotEndpoint(robot_id=f"rosy_{i:02d}", base_url=base, token="bench")
                 for i in range(1, n_robots + 1)]
    console = FleetConsole(endpoints, [HttpRobotClient(ep) for ep in endpoints])

    async def gather_all():
        await console.snapshot()

    async def run() -> list[float]:
        for _ in range(3):
            await gather_all()                      # 웜업 — 연결 풀을 데운다
        samples = []
        for _ in range(requests):
            started = time.perf_counter()
            await gather_all()
            samples.append((time.perf_counter() - started) * 1000.0)
        return samples

    try:
        samples = asyncio.run(run())
    finally:
        server.shutdown()
    ordered = sorted(samples)
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[int(len(ordered) * 0.95) - 1]
    return {
        "robots": n_robots, "requests": requests,
        "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
        "max_ms": round(max(ordered), 1),
        "mean_ms": round(statistics.fmean(ordered), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robots", type=int, required=True)
    parser.add_argument("--requests", type=int, default=40)
    args = parser.parse_args()
    print(json.dumps(measure(args.robots, args.requests), ensure_ascii=False))


if __name__ == "__main__":
    main()
