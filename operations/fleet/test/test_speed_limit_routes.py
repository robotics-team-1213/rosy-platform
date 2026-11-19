"""D-1005: the console route forwards a manual speed to CORE, names the operator, and adds no limit of its own."""
from types import SimpleNamespace

import pytest

pytest.importorskip("httpx")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.speed_limit_routes import install_speed_limit_routes
from fleet.swarm.transport import RobotApiError


class Client:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    async def speed_limits(self, body):
        self.calls.append(body)
        if self.error:
            raise self.error
        return {"limits": {"manual_linear": body.get("manual_linear")}}


def _app(client, allowed=True):
    app = FastAPI()

    def operator():
        if not allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=403)
        return SimpleNamespace(principal_id="person-a")

    install_speed_limit_routes(app, console=SimpleNamespace(clients=lambda: {"rosy_45": client}),
                               require_operator=operator, named_guard=[Depends(lambda: None)])
    return TestClient(app)


def test_the_speed_goes_to_core_with_the_operator_named():
    client = Client()
    response = _app(client).put("/api/fleet/robots/rosy_45/speed-limits", json={"manual_linear": 0.1, "manual_angular": 0.4})
    assert response.status_code == 200 and response.json()["limits"]["manual_linear"] == 0.1
    assert client.calls == [{"manual_linear": 0.1, "manual_angular": 0.4, "operator_name": "person-a"}]


def test_core_refusing_a_value_above_the_ceiling_reaches_the_console():
    client = Client(RobotApiError("rosy_45", 400, "VALIDATION_ERROR", "manual_linear 0.3 is above the signed ceiling 0.2", None))
    response = _app(client).put("/api/fleet/robots/rosy_45/speed-limits", json={"manual_linear": 0.3})
    assert response.status_code >= 400 and "ceiling" in response.text


@pytest.mark.parametrize("body", [{}, {"manual_linear": -1}, {"manual_linear": 0.1, "max_linear": 9}])
def test_bad_requests_never_reach_core(body):
    client = Client()
    assert _app(client).put("/api/fleet/robots/rosy_45/speed-limits", json=body).status_code in (400, 422)
    assert client.calls == []


def test_unknown_robot_and_non_operator_are_refused():
    assert _app(Client()).put("/api/fleet/robots/nope/speed-limits", json={"manual_linear": 0.1}).status_code == 404
    client = Client()
    assert _app(client, allowed=False).put("/api/fleet/robots/rosy_45/speed-limits",
                                           json={"manual_linear": 0.1}).status_code == 403 and client.calls == []
