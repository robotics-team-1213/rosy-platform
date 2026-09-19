"""core_api_web.api.app — FastAPI 팩토리 (P1-9, API-101). 계약: ROSY-API-REF-001."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from core_api_web.api.deps import CoreServicesLike
from core_api_web.api.errors import register_exception_handlers
from core_api_web.api.v1.routes import (
    control_router,
    events_router,
    logs_router,
    host_router,
    map_router,
    metrics_router,
    navigation_router,
    power_router,
    robot_router,
    safety_router,
    sensors_router,
    slam_router,
    swarm_router,
    system_router,
    waypoints_router,
    diagnostics_router,
    docking_router,
)
from core_api_web.api.ws import ws_router


def create_app(config: dict[str, Any], services: CoreServicesLike) -> FastAPI:
    app = FastAPI(
        title="ROSY CORE API",
        version="1.0.0",
        description="로봇 미들웨어 API — 계약: ROSY-API-REF-001 (v1.2)",
    )
    app.state.core = services
    # 현장 화면은 로봇 AP 위에서 뜬다. 대시보드 자산은 압축 없이 122 KB이고
    # gzip 뒤에는 29 KB다 — 첫 로드에서 93 KB가 줄어든다. 별도 런타임도,
    # 빌드 산출물도 늘리지 않으므로 D-23의 최소 표면 원칙을 지킨다.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    register_exception_handlers(app)

    web_root = Path(__file__).resolve().parent.parent / "web"
    dashboard_assets = {
        # tokens.css는 색의 단일 출처다(D-72 L1). styles.css보다 먼저 링크된다.
        # 이 allowlist는 `{asset_name:path}`가 슬래시를 허용하므로 경로 순회를
        # 막는 유일한 방어이기도 하다 — 디렉터리 스캔으로 바꾸지 않는다.
        "tokens.css": "text/css",
        "styles.css": "text/css",
        "app.js": "application/javascript",
        "map.js": "application/javascript",
        "triage.js": "application/javascript",
        "dom.js": "application/javascript",
        "client.js": "application/javascript",
        "settings.js": "application/javascript",
    }

    app.include_router(system_router)
    app.include_router(robot_router)
    app.include_router(control_router)
    app.include_router(safety_router)
    app.include_router(navigation_router)
    app.include_router(map_router)
    app.include_router(waypoints_router)
    app.include_router(events_router)
    app.include_router(diagnostics_router)
    app.include_router(logs_router)
    app.include_router(power_router)
    app.include_router(sensors_router)
    app.include_router(slam_router)
    app.include_router(docking_router)
    app.include_router(swarm_router)
    app.include_router(metrics_router)
    app.include_router(host_router)
    app.include_router(ws_router)

    @app.get("/api/v1", tags=["system"])
    def root() -> dict:
        return {"name": "core", "api_versions": ["v1"]}

    @app.get("/", include_in_schema=False)
    def dashboard_redirect():
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(
            web_root / "index.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": (
                    "default-src 'self'; connect-src 'self' ws: wss:; "
                    "img-src 'self' data:; style-src 'self'; script-src 'self'; "
                    "frame-ancestors 'none'; base-uri 'self'"
                ),
            },
        )

    @app.get("/dashboard/assets/{asset_name:path}", include_in_schema=False)
    def dashboard_asset(asset_name: str):
        media_type = dashboard_assets.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="dashboard asset not found")
        return FileResponse(
            web_root / asset_name,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
        )

    return app
