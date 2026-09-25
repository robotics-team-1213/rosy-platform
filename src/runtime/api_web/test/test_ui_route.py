"""D-129·D-1005 — 공용 L1 토큰 파일과 호환 경로. D-130.3 — 해시 고정."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core_api_web.api.app import create_app

WEB_ROOT = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"
TOKENS = Path(__file__).resolve().parents[3] / "hmi" / "web" / "tokens.css"

#: D-92 어휘 표의 열 이름 — 갤러리가 이 목록과 어긋나면 표와 갤러리가 두 개의
#: 사실이 된다(D-129 Consequences).
VOCABULARY = ("라벨", "값", "묶음 제목 줄", "값 격자", "버튼 셋", "필드",
              "태그", "오버레이 칩", "분류 머리", "증거·빈 상태")


def _client(config: dict | None = None) -> TestClient:
    return TestClient(create_app(config or {}, SimpleNamespace()))


def test_ui_tokens_serves_the_single_file():
    body = TOKENS.read_bytes()
    resp = _client().get("/ui/tokens.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert resp.content == body
    assert resp.headers["x-ui-tokens-sha256"] == hashlib.sha256(body).hexdigest()


def test_common_route_serves_only_the_declared_shared_assets():
    client = _client()
    assert client.get("/common/tokens.css").status_code == 200
    assert client.get("/common/components.css").status_code == 200
    assert client.get("/common/core_ui_logic.js").status_code == 200
    assert client.get("/common/ui.js").status_code == 200
    assert client.get("/common/template.html").status_code == 200
    assert "/api/v1/do" in client.get("/openapi.json").json()["paths"]
    assert client.get("/common/../api/app.py").status_code == 404


def test_styleguide_renders_the_whole_vocabulary_table():
    text = _client().get("/styleguide").text
    missing = [name for name in VOCABULARY if name not in text]
    assert not missing, f"갤러리가 어휘 표와 어긋난다: {missing}"


def test_styleguide_links_the_single_tokens_file():
    text = _client().get("/styleguide").text
    assert 'href="/common/tokens.css"' in text
    assert 'href="/styleguide/assets/styleguide.css"' in text
    assert "/dashboard/assets/" not in text, "갤러리는 대시보드 자산을 훔치지 않는다"


def test_styleguide_assets_allowlist_blocks_the_rest():
    client = _client()
    assert client.get("/styleguide/assets/styleguide.css").status_code == 200
    assert client.get("/styleguide/assets/secrets.env").status_code == 404
    assert client.get("/styleguide/assets/../api/app.py").status_code == 404


def test_release_pin_mismatch_warns_at_startup(caplog):
    with caplog.at_level(logging.WARNING, logger="core_api_web.api.app"):
        _client({"ui_tokens_sha256": "0" * 64})
    assert any("ui tokens sha mismatch" in r.message.lower() for r in caplog.records)


def test_no_pin_no_mismatch_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="core_api_web.api.app"):
        _client({})
    assert not [r for r in caplog.records if "ui tokens sha mismatch" in r.message.lower()]


def test_role_surface_pages_and_allowlisted_assets_are_served():
    client = _client()
    assert client.get("/console").status_code == 200
    assert "비상 정지" in client.get("/device").text
    assert client.get("/garage").status_code == 404
    assert client.get("/assets/panels/system/events.js").status_code == 200
    assert client.get("/assets/shell/shell.js").status_code == 200
    assert client.get("/assets/../../api/app.py").status_code == 404


def test_ui_manifest_contract_is_registered_in_openapi():
    schema = _client().get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/ui/surfaces/{surface}"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("UiSurfaceManifest")
    assert "UiPanelDescriptor" in schema["components"]["schemas"]


def test_surface_page_exposes_panel_mount_slots():
    body = _client().get("/device").text
    assert '<div class="surface-slot" data-slot="main"></div>' in body
    assert "<ui-slot" not in body
