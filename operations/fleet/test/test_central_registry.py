"""D-454 1단계 — 중앙 레지스트리 뷰(API Ref §10.1 읽기 2경로) 계약.

로스터가 정본이고 hub·발견은 보강이다. Fleet은 상태를 다시 계산하지 않는다(D-309) —
스냅샷의 증거 필드가 그대로 흐른다. 네트워크 없음, 가짜 객체만.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core_common.protocol.schemas import StateSnapshot
from fleet.server.central_registry import CentralRegistry
from fleet.server.central_registry_routes import install_central_registry_routes


class FakeRoster:
    def __init__(self, sources: dict[str, str]) -> None:
        self._sources = sources

    def robot_ids(self):
        return list(self._sources)

    def source_of(self, robot_id: str):
        return self._sources.get(robot_id)


class FakeHubRegistry:
    def __init__(self, records: dict[str, SimpleNamespace]):
        self._records = records

    def find(self, robot_id: str):
        return self._records.get(robot_id)


class FakeConsole:
    def __init__(self, registry) -> None:
        self.hub = SimpleNamespace(registry=registry)


class FakeDiscovery:
    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        return self._rows


def _registry():
    snapshot = StateSnapshot(robot_id="rosy_01", mode="NAVIGATION")
    snapshot_cap = StateSnapshot(robot_id="rosy_02")
    hub = FakeHubRegistry({
        "rosy_01": SimpleNamespace(online=True, snapshot=snapshot),
        "rosy_02": SimpleNamespace(online=False, snapshot=snapshot_cap),
        "rosy_03": SimpleNamespace(online=False, snapshot=None),
    })
    roster = FakeRoster({"rosy_02": "enrolled", "rosy_01": "static", "rosy_03": "enrolled"})
    discovery = FakeDiscovery([{"robot_id": "rosy_01", "address": "10.0.0.7"}])
    return CentralRegistry(roster, console=FakeConsole(hub), discovery=discovery)


def test_rows_merge_roster_hub_and_discovery_in_id_order():
    rows = _registry().rows()
    assert [row["robot_id"] for row in rows] == ["rosy_01", "rosy_02", "rosy_03"]
    first, second, third = rows
    assert first["source"] == "static" and first["online"] is True
    assert first["state"]["mode"] == "NAVIGATION"
    assert first["address_last_seen"] == "10.0.0.7"
    assert second["source"] == "enrolled" and second["online"] is False
    assert third["state"] is None and third["capabilities"] is None


def test_row_passes_robot_made_evidence_without_recomputation():
    row = _registry().row("rosy_01")
    # 로봇이 만든 스냅샷 필드가 바이트 그대로 흐른다(D-309) — Fleet은 다시 계산하지 않는다.
    assert row["state"] == StateSnapshot(robot_id="rosy_01", mode="NAVIGATION").model_dump(mode="json")


def test_unknown_robot_is_none_roster_is_source_of_truth():
    assert _registry().row("rosy_99") is None


@pytest.fixture
def client():
    app = FastAPI()
    install_central_registry_routes(app, _registry(),
                                    require_viewer=lambda: "viewer")
    return TestClient(app)


def test_list_and_detail_round_trip(client):
    body = client.get("/api/v1/fleet/robots").json()
    assert [row["robot_id"] for row in body["robots"]] == ["rosy_01", "rosy_02", "rosy_03"]
    detail = client.get("/api/v1/fleet/robots/rosy_02").json()
    assert detail["source"] == "enrolled" and detail["online"] is False


def test_unknown_robot_detail_is_404_unknown_robot(client):
    response = client.get("/api/v1/fleet/robots/rosy_99")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "UNKNOWN_ROBOT"


def test_viewer_role_is_required():
    def refuse():
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED"})

    app = FastAPI()
    install_central_registry_routes(app, _registry(), require_viewer=refuse)
    unauth = TestClient(app)
    assert unauth.get("/api/v1/fleet/robots").status_code == 401
