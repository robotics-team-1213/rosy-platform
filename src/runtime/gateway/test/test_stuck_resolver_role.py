"""D-438 §1: the stuck_resolver role answers stucks and reads; nothing else."""

import pytest

from test_line_follow_stuck_api import OPERATOR, URL, VIEWER, _stuck

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
RESOLVER = {"Authorization": "Bearer fleet-stuck-resolver-token-0001"}


def _resolver(client) -> dict:
    made = client.post("/api/v1/system/tokens", headers=ADMIN, json={
        "role": "stuck_resolver", "label": "site:fleet-resolver",
        "token": "fleet-stuck-resolver-token-0001"})
    assert made.status_code == 201, made.text
    return RESOLVER


@pytest.mark.parametrize("who,expected", [("viewer", 403), ("operator", 200), ("resolver", 200)])
def test_stuck_decision_needs_stuck_decide(core_client, who, expected):
    client, _, stuck_id = _stuck(core_client)
    headers = {"viewer": VIEWER, "operator": OPERATOR}.get(who) or _resolver(client)
    response = client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=headers)
    assert response.status_code == expected, response.text


def test_resolver_reads_but_cannot_drive_or_release(core_client):
    client, _, _ = _stuck(core_client)
    headers = _resolver(client)
    assert client.get("/api/v1/line-follow", headers=headers).status_code == 200
    assert client.get("/api/v1/robot/state", headers=headers).status_code == 200
    assert client.put("/api/v1/line-follow/mode", json={"mode": "OFF"},
                      headers=headers).status_code == 403
    assert client.post("/api/v1/safety/release", headers=headers).status_code == 403
    assert client.post("/api/v1/teleop", json={"linear": 0.0, "angular": 0.0},
                       headers=headers).status_code == 403
