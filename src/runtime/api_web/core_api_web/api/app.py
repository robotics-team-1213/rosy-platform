"""core_api_web.api.app — FastAPI 팩토리 (P1-9, API-101). 계약: ROSY-API-REF-001 v1.63."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import HTMLResponse
from core_api_web.api.ui_registry import load_registry

from core_api_web.api.deps import CoreServicesLike, refused_token_count
from core_api_web.api.errors import register_exception_handlers
from core_api_web.api.v1.auth import PairingState
from core_api_web.api.v1.routes import (
    auth_router,
    control_router,
    events_router,
    logs_router,
    line_follow_router,
    host_router,
    intent_router,
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
    ui_router,
)
from core_api_web.api.ws import ws_router


#: One policy for every operator page CORE renders (/dashboard and the role
#: surfaces). Assets are same-origin; the live feed is a websocket.
OPERATOR_PAGE_CSP = (
    "default-src 'self'; connect-src 'self' ws: wss:; "
    "img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'"
)
OPERATOR_PAGE_HEADERS = {"Cache-Control": "no-cache", "Content-Security-Policy": OPERATOR_PAGE_CSP}


def _web_common_root() -> Path:
    """Resolve installed assets first, with a source-tree fallback for host tests.

    A web_common directory is one that ships ``manifest.json``."""
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("web_common"))
        if (share / "manifest.json").is_file():
            return share
    except (ImportError, LookupError):
        pass
    return Path(__file__).resolve().parents[4] / "hmi" / "web_common"


def _shared_assets(web_common: Path) -> dict[str, str]:
    """name -> media type, from web_common's manifest (the one /common allowlist)."""
    manifest = json.loads((web_common / "manifest.json").read_text(encoding="utf-8"))
    return dict(manifest["shared_assets"])


def _dashboard_root() -> Path:
    """Operator screens live in hmi. The installed share wins; the source tree is the host fallback."""
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("dashboard"))
        if (share / "index.html").is_file():
            return share
    except (ImportError, LookupError):
        pass
    return Path(__file__).resolve().parents[4] / "hmi" / "dashboard"


def _pilot_root() -> Path:
    """Teleop surface (D-323). Same resolution rule as the dashboard."""
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("pilot"))
        if (share / "index.html").is_file():
            return share
    except (ImportError, LookupError):
        pass
    return Path(__file__).resolve().parents[4] / "hmi" / "pilot"


def create_app(config: dict[str, Any], services: CoreServicesLike) -> FastAPI:
    app = FastAPI(
        title="ROSY CORE API",
        version="1.20.0",
        description="로봇 미들웨어 API — 계약: ROSY-API-REF-001 (v1.63)",
    )
    app.state.core = services
    app.state.pairing = PairingState()
    refused = refused_token_count(config)
    if refused:
        # D-193 7: a device never accepts the shared dev tokens or plaintext
        # entries, whichever layer brought them in. Say so once at start.
        logging.warning("device mode refused %d development or plaintext API token(s)", refused)
        services.events.publish("auth.credentials_refused", severity="warning", source="api",
                                data={"count": refused})
    # 현장 화면은 로봇 AP 위에서 뜬다. 대시보드 자산은 압축 없이 122 KB이고
    # gzip 뒤에는 29 KB다 — 첫 로드에서 93 KB가 줄어든다. 별도 런타임도,
    # 빌드 산출물도 늘리지 않으므로 D-23의 최소 표면 원칙을 지킨다.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    register_exception_handlers(app)

    web_root = _dashboard_root()
    registry = load_registry(web_root / "panels.yaml", web_root)
    app.state.ui_registry = registry
    dashboard_assets = {
        # tokens.css는 색의 단일 출처다(D-72 L1). styles.css보다 먼저 링크된다.
        # 이 allowlist는 `{asset_name:path}`가 슬래시를 허용하므로 경로 순회를
        # 막는 파일시스템 방어목적이므로 폴더 스캔으로 바꾸지 않는다.
        "styles.css": "text/css",
        "app.js": "application/javascript",
        "map.js": "application/javascript",
        "host-cards.js": "application/javascript",
        "ros-network.js": "application/javascript",
        "triage.js": "application/javascript",
        "dom.js": "application/javascript",
        "client.js": "application/javascript",
        "settings.js": "application/javascript",
        "vision.js": "application/javascript",
        "camera-capture.js": "application/javascript",
        "status-summary.js": "application/javascript",
        "surface-navigation.js": "application/javascript",
        "shell/shell.js": "application/javascript",
        "shell/store.js": "application/javascript",
        "shell/mount.js": "application/javascript",
        "shell/shell.css": "text/css",
        "panels/setup/pose-evidence.js": "application/javascript",
        **registry.assets(),
    }

    app.include_router(auth_router)
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
    app.include_router(intent_router)
    app.include_router(ws_router)
    app.include_router(ui_router)

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
            headers=dict(OPERATOR_PAGE_HEADERS),
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

    # D-323 — Rosy Pilot 조종 표면. dashboard와 같은 정적 파일·allowlist 규칙.
    pilot_root = _pilot_root()
    pilot_assets = {
        # 이 allowlist도 {asset_name:path}의 경로 순회 방어다. 모듈이 늘 때마다 여기에 등록.
        "styles.css": "text/css",
        "stick.js": "application/javascript",
        "link.js": "application/javascript",
        "app.js": "application/javascript",
        "client.js": "application/javascript",
        "drivers/registry.js": "application/javascript",
        "drivers/pinky_core.js": "application/javascript",
        "autonomy.js": "application/javascript",
        "screens/connect.js": "application/javascript",
        "screens/drive.js": "application/javascript",
        "screens/drive-auto.js": "application/javascript",
        "screens/drive-view.js": "application/javascript",
        "screens/inputs.js": "application/javascript",
        "input-state.js": "application/javascript",
        "vision.js": "application/javascript",
        "manifest.webmanifest": "application/manifest+json",
        "sw.js": "application/javascript",
        "icons/icon-192.png": "image/png",
        "icons/icon-192-maskable.png": "image/png",
        "icons/icon-512.png": "image/png",
    }

    @app.get("/pilot", include_in_schema=False)
    def pilot():
        return FileResponse(
            pilot_root / "index.html",
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

    @app.get("/pilot/assets/{asset_name:path}", include_in_schema=False)
    def pilot_asset(asset_name: str):
        media_type = pilot_assets.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="pilot asset not found")
        headers = {"Cache-Control": "no-cache"}
        if asset_name == "sw.js":
            # scope /pilot 은 스크립트 디렉터리(/pilot/assets)보다 넓다 — 허용 헤더 필수(D-365).
            headers["Service-Worker-Allowed"] = "/pilot"
        return FileResponse(
            pilot_root / asset_name,
            media_type=media_type,
            headers=headers,
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

    common_assets = _shared_assets(web_common)

    @app.get("/common/{asset_name:path}", include_in_schema=False)
    def common_asset(asset_name: str):
        media_type = common_assets.get(asset_name)
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

    @app.get("/assets/{asset_name:path}", include_in_schema=False)
    def ui_asset(asset_name: str):
        media_type = dashboard_assets.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="UI asset not found")
        return FileResponse(web_root / asset_name, media_type=media_type, headers={"Cache-Control": "no-cache"})

    surface_template = (web_root / "surface.html").read_text(encoding="utf-8")

    @app.get("/{surface}", include_in_schema=False)
    def surface_page(surface: str):
        definition = registry.surfaces.get(surface)
        if definition is None:
            raise HTTPException(status_code=404, detail="surface not found")
        slots = "".join(f'<div class="surface-slot" data-slot="{slot}"></div>' for slot in definition.slots)
        html = (surface_template.replace("{{title}}", definition.title)
                .replace("{{surface}}", definition.id).replace("{{grammar}}", definition.grammar)
                .replace("{{slots}}", slots))
        return HTMLResponse(html, headers=dict(OPERATOR_PAGE_HEADERS))

    return app
