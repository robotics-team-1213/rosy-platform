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
    "cell.js": ("cell/cell.js", "application/javascript"),
    "cell-document-editor.js": ("cell/cell-document-editor.js", "application/javascript"),
    "cell.css": ("cell/cell.css", "text/css"),
    "doc-tabs.css": ("shared/doc-tabs.css", "text/css"),
    "fleet-header.css": ("shared/fleet-header.css", "text/css"),
    "fleet-header.js": ("shared/fleet-header.js", "application/javascript"),
    "styles.css": ("shared/styles.css", "text/css"),
    "console.js": ("console.js", "application/javascript"),
    "confirmed-action.js": ("confirmed-action.js", "application/javascript"),
    "install.js": ("install.js", "application/javascript"),
    "peer-picker.js": ("peer-picker.js", "application/javascript"),
    "address-drift.js": ("shared/address-drift.js", "application/javascript"),
    "state-age.js": ("state-age.js", "application/javascript"),
    "authorization.js": ("shared/authorization.js", "application/javascript"),
    "development-auth.js": ("shared/development-auth.js", "application/javascript"),
    "password-login.js": ("shared/password-login.js", "application/javascript"),
    "password-login.css": ("shared/password-login.css", "text/css"),
    "camera-pairing.js": ("camera-pairing.js", "application/javascript"),
    "camera-peer.js": ("camera-peer.js", "application/javascript"),
    "field-layers.js": ("field-layers.js", "application/javascript"),
    "field-view.js": ("field-view.js", "application/javascript"),
    "field-warp.js": ("shared/field-warp.js", "application/javascript"),
    "formation.js": ("formation.js", "application/javascript"),
    "motion-readiness.js": ("motion-readiness.js", "application/javascript"),
    "line-stuck.js": ("line-stuck.js", "application/javascript"),
    "trip-replan.js": ("trip-replan.js", "application/javascript"),
    "link-tag.js": ("link-tag.js", "application/javascript"),
    "site-path.js": ("site-path.js", "application/javascript"),
    "localization-badge.js": ("localization-badge.js", "application/javascript"),
    "camera-warp.js": ("camera-warp.js", "application/javascript"),
    "camera-backdrop.js": ("camera-backdrop.js", "application/javascript"),
    "map-fit.js": ("shared/map-fit.js", "application/javascript"),
    "map-fit-view.js": ("map-fit-view.js", "application/javascript"),
    "map-view.js": ("map-view.js", "application/javascript"),
    "poll-gate.js": ("shared/poll-gate.js", "application/javascript"),
    "roster.js": ("roster.js", "application/javascript"),
    "queues.js": ("queues.js", "application/javascript"),
    "card-trip.js": ("card-trip.js", "application/javascript"),
    "power-health-view.js": ("power-health-view.js", "application/javascript"),
    "enrollment.js": ("enrollment.js", "application/javascript"),
    "signals.js": ("signals.js", "application/javascript"),
    "site-map.css": ("site-map.css", "text/css"),
    "site-map.js": ("site-map.js", "application/javascript"),
    "site-map-model.js": ("shared/site-map-model.js", "application/javascript"),
    "site-map-teach.js": ("site-map-teach.js", "application/javascript"),
    "site-layer.js": ("site-layer.js", "application/javascript"),
    "tracking-layer.js": ("tracking-layer.js", "application/javascript"),
    "tracking-view.js": ("tracking-view.js", "application/javascript"),
    "tracking-relearn.js": ("tracking-relearn.js", "application/javascript"),
    "start-point-layer.js": ("start-point-layer.js", "application/javascript"),
    "start-point-view.js": ("start-point-view.js", "application/javascript"),
    "trail-view.js": ("trail-view.js", "application/javascript"),
    "traffic-view.js": ("traffic-view.js", "application/javascript"),
    "guide-layer.js": ("shared/guide-layer.js", "application/javascript"),
    "connection-view.js": ("connection-view.js", "application/javascript"),
    "vision-view.js": ("shared/vision-view.js", "application/javascript"),
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
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        """Minimal process liveness for local container supervision."""
        return {"status": "ok"}

    @app.get("/console/cell", include_in_schema=False)
    def cell_page():
        return FileResponse(
            WEB_ROOT / "cell" / "cell.html", media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP},
        )

    # D-488 — 현장 지도(주소·차로) 보기·초안 편집·경로 미리보기.
    @app.get("/console/site-map", include_in_schema=False)
    def site_map_page():
        return FileResponse(
            WEB_ROOT / "site-map.html", media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP},
        )

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
        # D-518: the public name stays the key. The value is the file under web/.
        entry = CONSOLE_ASSETS.get(asset_name)
        if entry is None:
            raise HTTPException(status_code=404, detail="console asset not found")
        relative, media_type = entry
        path = (WEB_ROOT / relative).resolve()
        root = WEB_ROOT.resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="console asset not found")
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})
