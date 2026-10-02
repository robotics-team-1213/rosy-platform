"""D-411 A: CORE recording control, download gate and teleop intent evidence."""

import pytest

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


def test_teleop_rejected_before_the_manager_is_still_evidence(core_client):
    client, svc = core_client()
    seen = []
    svc.command.intent_sink = lambda **fields: seen.append(fields)
    svc.capability._data["teleop"] = False
    response = client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert response.status_code == 501
    assert seen and seen[0]["accepted"] is False and seen[0]["code"] == "CAPABILITY_NOT_SUPPORTED"
