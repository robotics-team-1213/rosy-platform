"""core_api_web.api.app — FastAPI 팩토리 (P1-9, API-101). 계약: ROSY-API-REF-001."""

from __future__ import annotations

import hashlib
import logging
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
    line_follow_router,
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
    traffic_router,
    vision_router,
    waypoints_router,
    diagnostics_router,
    docking_router,
)


def _web_common_root() -> Path:
    """Resolve installed assets first, with a source-tree fallback for host tests."""
    try:
        from ament_index_python.packages import get_package_share_directory

        return Path(get_package_share_directory("web_common"))
    except (ImportError, LookupError):
        return Path(__file__).resolve().parent.parent.parent.parent / "web_common"
from core_api_web.api.ws import ws_router


def create_app(config: dict[str, Any], services: CoreServicesLike) -> FastAPI:
    app = FastAPI(
        title="ROSY CORE API",
        version="1.16.0",
        description="로봇 미들웨어 API — 계약: ROSY-API-REF-001 (v1.16)",
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
        # 막는 파일시스템 방어목적이므로 폴더 스캔으로 바꾸지 않는다.
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
    app.include_router(line_follow_router)
    app.include_router(traffic_router)
    app.include_router(vision_router)
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
                    "img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
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

    # D-129 — 토큰 파일은 트리 전체에서 하나다. 모든 웹 표면이 이 한 파일을
    # /ui/tokens.css 로 링크하고 각자 사본을 두지 않는다. D-130.3 — 릴리스가
    # 핀을 걸면 기동 때 어긋남을 경고한다(사이트 PC 서버가 로봇 이미지보다
    # 낡은 토큰을 서빙하는 버전 스큐).
    web_common = _web_common_root()
    ui_tokens = web_common / "tokens.css"
    ui_tokens_sha = hashlib.sha256(ui_tokens.read_bytes()).hexdigest()
    pinned_sha = config.get("ui_tokens_sha256")
    if pinned_sha and pinned_sha != ui_tokens_sha:
        logging.warning(
            "ui tokens sha mismatch: pinned %s, serving %s (%s)",
            pinned_sha, ui_tokens_sha, ui_tokens,
        )

    @app.get("/common/{asset_name:path}", include_in_schema=False)
    def common_asset(asset_name: str):
        valid_assets = {
            "tokens.css": "text/css",
            "core_ui_logic.js": "application/javascript"
        }
        media_type = valid_assets.get(asset_name)
        if not media_type:
            raise HTTPException(status_code=404, detail="common asset not found")
        return FileResponse(web_common / asset_name, media_type=media_type, headers={"Cache-Control": "no-cache"})

    @app.get("/ui/tokens.css", include_in_schema=False)
    def ui_tokens_asset():
        return FileResponse(
            ui_tokens,
            media_type="text/css",
            headers={
                "Cache-Control": "no-cache",
                "X-UI-Tokens-Sha256": ui_tokens_sha,
            },
        )

    @app.get("/styleguide", include_in_schema=False)
    def styleguide():
        # D-129.3 — D-92 어휘 표의 유일한 렌더링. 제품 표면이 아니라 어휘 표의
        # 실행 가능한 사본이며 어디에서도 import 되지 않는다.
        return FileResponse(
            web_root / "styleguide.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": (
                    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                    "script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
                ),
            },
        )

    styleguide_assets = {"styleguide.css": "text/css"}

    @app.get("/styleguide/assets/{asset_name:path}", include_in_schema=False)
    def styleguide_asset(asset_name: str):
        media_type = styleguide_assets.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="styleguide asset not found")
        return FileResponse(web_root / asset_name, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})

    return app
