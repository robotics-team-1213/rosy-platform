"""콘솔 정적 자산 — 페이지와 자산 allowlist (D-129, D-157).

경로 순회를 막는 유일한 방어는 allowlist 다 — 디렉터리 스캔으로 바꾸지 않는다
(core 와 같은 규칙). 공용 L1 자산은 서버가 설정받은 web_common 디렉터리의
shared-assets.json 이 명시한 파일만 /common 아래로 서빙한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

WEB_ROOT = Path(__file__).resolve().parent / "web"

CONSOLE_ASSETS = {
    "styles.css": "text/css",
    "console.js": "application/javascript",
    "install.js": "application/javascript",
    "address-drift.js": "application/javascript",
    "authorization.js": "application/javascript",
    "camera-pairing.js": "application/javascript",
    "field-layers.js": "application/javascript",
    "field-view.js": "application/javascript",
    "formation.js": "application/javascript",
    "line-stuck.js": "application/javascript",
    "localization-badge.js": "application/javascript",
    "map-fit.js": "application/javascript",
    "map-fit-view.js": "application/javascript",
    "map-view.js": "application/javascript",
    "poll-gate.js": "application/javascript",
    "roster.js": "application/javascript",
    "enrollment.js": "application/javascript",
    "signals.js": "application/javascript",
    "site-layer.js": "application/javascript",
    "vision-view.js": "application/javascript",
}

CONSOLE_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


def shared_assets(root: Optional[Path]) -> dict[str, str]:
    """The /common allowlist is web_common's shared-assets.json. A configured
    directory without one (a trimmed copy) uses the default web_common's."""
    manifest = root / "shared-assets.json" if root is not None else None
    if manifest is None or not manifest.is_file():
        from fleet.cli import default_web_common

        manifest = default_web_common() / "shared-assets.json"
    return dict(json.loads(manifest.read_text(encoding="utf-8"))["shared_assets"])


def install_static_routes(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/console")

    @app.get("/console", include_in_schema=False)
    def console_page():
        return FileResponse(
            WEB_ROOT / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP},
        )

    # D-410 — 설치·보정 화면. 기기 등록·카메라 연결 승인·경기장/맵 보정이 산다.
    # 운용(감시·목표·정지)은 /console 에 그대로 있다.
    @app.get("/console/install", include_in_schema=False)
    def console_install_page():
        return FileResponse(
            WEB_ROOT / "install.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP},
        )

    common_assets = shared_assets(app.state.web_common)

    @app.get("/common/{asset_name:path}", include_in_schema=False)
    def common_asset(asset_name: str):
        media_type = common_assets.get(asset_name)
        root = app.state.web_common
        if media_type is None:
            raise HTTPException(status_code=404, detail="common asset not found")
        if root is None or not root.is_dir():
            raise HTTPException(
                status_code=404,
                detail={"code": "WEB_COMMON_UNCONFIGURED",
                        "message": "--web-common 가 설정되지 않았다"},
            )
        path = root / asset_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="common asset not found")
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})

    @app.get("/ui/tokens.css", include_in_schema=False)
    def legacy_ui_tokens_asset():
        return common_asset("tokens.css")

    @app.get("/console/assets/{asset_name:path}", include_in_schema=False)
    def console_asset(asset_name: str):
        media_type = CONSOLE_ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="console asset not found")
        return FileResponse(WEB_ROOT / asset_name, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})
