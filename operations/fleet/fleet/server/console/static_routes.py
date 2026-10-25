"""콘솔 정적 자산 — 페이지와 자산 allowlist (D-129, D-157).

경로 순회를 막는 유일한 방어는 allowlist 다 — 디렉터리 스캔으로 바꾸지 않는다
(core 와 같은 규칙). 공용 L1 자산은 서버가 설정받은 web_common 디렉터리의
shared-assets.json 이 명시한 파일만 /common 아래로 서빙한다.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from fleet._source_layout import console_root
from fleet.server.learning_entry import install_learning_routes

WEB_ROOT = console_root()

_asset_api = runpy.run_path(str(WEB_ROOT / "asset_registry.py"))
_REGISTRY = _asset_api["load_registry"](WEB_ROOT)
_resolve_entry = _asset_api["resolve_entry"]
CONSOLE_ASSETS = {name: (entry["path"], entry["media_type"])
                  for name, entry in _REGISTRY["assets"].items()}

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
    install_learning_routes(app, WEB_ROOT, CONSOLE_CSP)

    def page_handler(url):
        def page():
            entry = _resolve_entry(WEB_ROOT, _REGISTRY["pages"], url)
            if entry is None:
                raise HTTPException(status_code=404, detail="console page not found")
            path, media_type = entry
            return FileResponse(path, media_type=media_type,
                                headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP})
        return page

    for url in _REGISTRY["pages"]:
        app.add_api_route(url, page_handler(url), methods=["GET"], include_in_schema=False,
                          name="console-page:" + url)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/console")

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
