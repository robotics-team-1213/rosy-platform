"""D-343 로비 잔여 — `GET /api/v1/site/rooms` 계약 (CORE Avahi `_rosy._tcp` 탐색).

행은 공개 정보만 싣는다(토큰·비밀 없음). Avahi 가 없으면 503 —
기기에서 받지 못한 이유를 숨기지 않는다.
"""

from __future__ import annotations

from fastapi import FastAPI

from core_api_web.api.v1.rooms import rooms_router, scan_robots
from core_common.protocol import discovery_txt

_TXT = ";".join([
    "proto=core-v1", "role=robot", "tls=none", "product=rosy",
    "name=rosy-01", "release=2026.10.04-034", "model=pinky_pro",
])


def _line(host, port=8080):
    return f"=;eth0;IPv4;rosy-01;_rosy._tcp;local;{host};10.0.0.{port % 250};{port};{_TXT}"


def test_scan_sorts_and_shapes_rooms_with_join_urls():
    rows = scan_robots(browse=lambda timeout_s: [
        {"hostname": "rosy-02", "address": "10.0.0.8", "port": 8080,
         "kind": "robot", "url": "http://rosy-02.local:8080/pilot/#join"},
    ])
    assert rows[0]["url"] == "http://rosy-02.local:8080/pilot/#join"
    assert set(rows[0]) == {"hostname", "address", "port", "kind", "url"}
    assert "token" not in rows[0] and "secret" not in rows[0]


def test_scan_drops_wrong_type_and_rejects_hostnames():
    verdict_ok = discovery_txt.classify(
        "_rosy._tcp", "rosy-01.local", "10.0.0.7", 8080,
        [("product", "rosy"), ("role", "robot"), ("proto", "core-v1"), ("tls", "none")])
    assert verdict_ok.__class__.__name__ == "Accepted"
    # 같은 자리에서 _rosy-fleet._tcp 는 이 탐색의 방이 아니다.
    verdict = discovery_txt.classify(
        "_rosy-fleet._tcp", "rosy-01", "10.0.0.7", 8080, [])
    assert verdict.__class__.__name__ == "Rejected"


def _client():
    app = FastAPI()
    app.include_router(rooms_router)
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_rooms_endpoint_serves_injected_rows(monkeypatch):
    from core_api_web.api.v1 import rooms as rooms_module

    monkeypatch.setattr(
        rooms_module, "scan_robots",
        lambda *, timeout_s=4.0: [{"hostname": "rosy-01", "address": "10.0.0.7",
                                   "port": 8080, "kind": "robot",
                                   "url": "http://rosy-01.local:8080/pilot/#join"}])
    client = _client()
    response = client.get("/api/v1/site/rooms")
    assert response.status_code == 200
    assert response.json() == {"rooms": [
        {"hostname": "rosy-01", "address": "10.0.0.7", "port": 8080,
         "kind": "robot", "url": "http://rosy-01.local:8080/pilot/#join"}]}


def test_rooms_endpoint_returns_503_when_avahi_is_missing(monkeypatch):
    from core_api_web.api.v1 import rooms as rooms_module

    def _missing(*, timeout_s):
        from core_api_web.api.v1.rooms import _Unavailable
        raise _Unavailable("avahi-browse is unavailable: [Errno 2]")

    monkeypatch.setattr(rooms_module, "scan_robots", _missing)
    client = _client()
    response = client.get("/api/v1/site/rooms")
    assert response.status_code == 503
    assert response.json()["code"] == "DISCOVERY_UNAVAILABLE"
