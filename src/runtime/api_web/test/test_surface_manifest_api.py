from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_api_web.api.deps import AuthContext, auth_dependency, get_services
from core_api_web.api.errors import ApiError, register_exception_handlers
from core_api_web.api.ui_registry import load_registry
from core_api_web.api.v1.ui import ui_router


class _Capability:
    def to_dict(self):
        return {}


def _surface_client(role=None):
    app = FastAPI()
    register_exception_handlers(app)
    app.state.ui_registry = load_registry(
        Path(__file__).resolve().parents[3] / "hmi" / "dashboard" / "panels.yaml",
        Path(__file__).resolve().parents[3] / "hmi" / "dashboard",
    )
    app.state.core = SimpleNamespace(
        config={"runtime": {"mode": "full"}},
        # CAP-001 임계값 계약: `runtime_truth()` 는 state.received_age() 를 본다 (D-32).
        # 이 스텁은 샘플을 주지 않으므로 "아직 온 샘플 없음"으로 응답한다.
        state=SimpleNamespace(received_age=lambda channel: None),
        capability=_Capability(), inventory=lambda: {"descriptors": []},
    )
    def auth():
        if role is None:
            raise ApiError("UNAUTHORIZED", 401, "missing or invalid token")
        return AuthContext("test", role)
    app.dependency_overrides[auth_dependency] = auth
    app.dependency_overrides[get_services] = lambda: app.state.core
    app.include_router(ui_router)
    return TestClient(app)


def test_surface_manifest_auth_role_and_unknown_statuses():
    assert _surface_client().get("/api/v1/ui/surfaces/console").status_code == 401
    assert _surface_client("viewer").get("/api/v1/ui/surfaces/setup").status_code == 403
    assert _surface_client("administrator").get("/api/v1/ui/surfaces/garage").status_code == 404
    response = _surface_client("administrator").get("/api/v1/ui/surfaces/device")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["surfaces"]] == ["console", "setup", "device"]
