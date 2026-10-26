"""The intent adapter preserves Home's caller epoch before any mutation."""
from uuid import uuid4

import pytest

from core_features.waypoints.manager import Waypoint

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


class Executor:
    def __init__(self):
        self.sent = []

    def send_goal(self, spec, *, correlation_id=None):
        self.sent.append((spec, correlation_id))

    def cancel_goal(self):
        pass


@pytest.mark.parametrize("invalid", ["boot", "generation"])
def test_home_intent_preserves_epoch_and_accepts_a_valid_pair(core_client, monkeypatch, invalid):
    client, services = core_client()
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    services.nav.executor = executor = Executor()
    services.nav._waypoints.create(Waypoint(name="__home__", x=0.0, y=0.0))
    before = services.nav.native_readback()["owner"]
    mode = services.modes.mode
    pair = {"expected_boot_id": before["boot_id"],
            "expected_owner_generation": before["owner_generation"]}
    wrong = dict(pair)
    if invalid == "boot":
        wrong["expected_boot_id"] = str(uuid4())
        assert wrong["expected_boot_id"] != pair["expected_boot_id"]
    else:
        wrong["expected_owner_generation"] += 1
    response = client.post("/api/v1/do", headers=OPERATOR, json={"do": "home", **wrong})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "OWNER_GENERATION_CHANGED"
    assert services.nav.native_readback()["owner"] == before
    assert services.modes.mode is mode and executor.sent == []
    response = client.post("/api/v1/do", headers=OPERATOR, json={"do": "home", **pair})
    assert response.status_code == 200, response.text
    assert response.json()["steps"][0]["result"]["operation"]["kind"] == "home"
    assert len(executor.sent) == 1
