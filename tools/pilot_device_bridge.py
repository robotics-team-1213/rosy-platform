#!/usr/bin/env python3
"""개발용 pilot 중계: 이 PC 가 pilot 정적 자산을 서빙하고 /api·/ws 는 실기 CORE 로 넘긴다.

로봇 이미지에 pilot 이 아직 없을 때(D-323 병합 전) 실기 주행을 시험하는 다리다. 브라우저에게는
한 출처(same-origin)로 보이므로 로봇이 직접 서빙할 때와 같은 코드 경로를 탄다. 운영 경로가
아니다 — 운영은 CORE 가 /pilot 을 서빙한다(D-323 §3).

    python tools/pilot_device_bridge.py --robot http://rosy-pinky-8kcn.local:8080 --port 8081
    adb reverse tcp:8081 tcp:8081   # 태블릿에서 http://localhost:8081/pilot/

토큰은 이 다리가 저장하지 않는다. Authorization 헤더와 WS 첫 프레임을 그대로 흘려보낸다.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "src" / "hmi" / "pilot"
COMMON = ROOT / "src" / "hmi" / "web"
TYPES = {".js": "application/javascript", ".css": "text/css", ".html": "text/html",
         ".webmanifest": "application/manifest+json", ".png": "image/png", ".json": "application/json"}
# 요청·응답에서 다리가 다시 계산해야 하는 홉 단위 헤더.
HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade",
       "accept-encoding", "content-encoding"}


def _file(base: Path, rel: str) -> Response:
    target = (base / rel).resolve()
    if base.resolve() not in target.parents or not target.is_file() or "test" in target.parts:
        return Response(status_code=404)
    headers = {"Cache-Control": "no-cache"}
    if target.name == "sw.js":
        headers["Service-Worker-Allowed"] = "/pilot"   # scope 가 스크립트 디렉터리보다 넓다
    return FileResponse(target, media_type=TYPES.get(target.suffix, "application/octet-stream"),
                        headers=headers)


def build_app(robot: str) -> Starlette:
    client = httpx.AsyncClient(base_url=robot, timeout=httpx.Timeout(5.0, connect=3.0))
    ws_base = robot.replace("http://", "ws://").replace("https://", "wss://")

    async def pilot_index(request: Request) -> Response:
        return _file(PILOT, "index.html")

    async def pilot_asset(request: Request) -> Response:
        return _file(PILOT, request.path_params["path"])

    async def common_asset(request: Request) -> Response:
        return _file(COMMON, request.path_params["path"])

    async def api(request: Request) -> Response:
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        upstream = await client.request(request.method, request.url.path,
                                        params=request.query_params, headers=headers,
                                        content=await request.body())
        out = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP}
        return Response(upstream.content, status_code=upstream.status_code, headers=out)

    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            async with websockets.connect(ws_base + websocket.url.path, open_timeout=5) as up:
                async def down_to_up():
                    while True:
                        await up.send(await websocket.receive_text())

                async def up_to_down():
                    async for message in up:
                        await websocket.send_text(message if isinstance(message, str) else message.decode())

                tasks = [asyncio.create_task(down_to_up()), asyncio.create_task(up_to_down())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                code = up.close_code or 1000
        except (WebSocketDisconnect, OSError, websockets.WebSocketException):
            code = 1011
        try:
            await websocket.close(code=code)
        except RuntimeError:
            pass   # 이미 닫혔다

    return Starlette(routes=[
        Route("/", lambda request: RedirectResponse("/pilot/")),
        Route("/pilot", pilot_index),
        Route("/pilot/", pilot_index),
        Route("/pilot/assets/{path:path}", pilot_asset),
        Route("/common/{path:path}", common_asset),
        Route("/api/{rest:path}", api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
        WebSocketRoute("/ws/{rest:path}", ws),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--robot", required=True, help="실기 CORE, 예: http://rosy-pinky-8kcn.local:8080")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    uvicorn.run(build_app(args.robot.rstrip("/")), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
