"""D-760 rev 3 item 9: ``line_follow.regulation_wait`` reaches GET /robot/state and GET /line-follow."""
from dataclasses import replace

from core_features.line_follow.manager import LineFollowMode, LineObservation

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


def _tick(services):
    services.line_follow.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=1.0,
                                                 visible=True, error=0.0, confidence=0.9))
    services.line_follow.tick()
    services.state.set_line_follow(services.line_follow.status())


def test_regulation_wait_in_snapshot_and_line_follow(core_client):
    client, services = core_client()
    assert client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]["regulation_wait"] is None
    client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=OPERATOR)
    _tick(services)
    assert client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]["regulation_wait"] is None

    lf = services.line_follow
    lf._config = replace(lf.config, authority_required=True)
    _tick(services)
    snapshot = client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]
    assert (snapshot["regulation_wait"], snapshot["reason"]) == ("authority", "authority_none")
    assert client.get("/api/v1/line-follow", headers=VIEWER).json()["regulation_wait"] == "authority"
