"""D-525: POST /api/v1/line-follow/advice is display only — stored, shown, never read by a decision."""
import ast
from pathlib import Path

from core_features.line_follow.model import LineFollowMode, LineObservation

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
URL = "/api/v1/line-follow/advice"
ROOT = Path(__file__).resolve().parents[4]
FEATURES = ROOT / "middleware/core/services/core_features"


def _body(**fields):
    return {"advice_id": "a1", "leg_id": "trip-1:0", "seq": 1, "fleet_epoch": "e1",
            "pose_stamp": 1_800_000_000.0, "ttl_s": 2.0,
            "signal": {"signal_id": "S1", "approach": "north", "stop_m": 0.8, "lamp": "red",
                       "left_s": 3.0, "green_in_s": None, "exact": True, "may_enter": False},
            **fields}


def test_viewer_is_forbidden(core_client):
    client, _ = core_client()
    assert client.post(URL, json=_body(), headers=VIEWER).status_code == 403


def test_post_then_get_shows_advice_without_line_follow_active(core_client):
    client, _ = core_client()
    assert "advice" not in client.get("/api/v1/line-follow", headers=VIEWER).json()
    assert client.post(URL, json=_body(), headers=OPERATOR).json() == {"accepted": True, "reason": None}
    shown = client.get("/api/v1/line-follow", headers=VIEWER).json()["advice"]
    assert shown["advice_id"] == "a1" and shown["signal"]["lamp"] == "red"
    assert 0 < shown["expires_in_s"] <= 2.0
    assert client.post(URL, json=_body(seq=0), headers=OPERATOR).json() == {"accepted": False,
                                                                           "reason": "stale"}


def test_bad_ttl_is_a_validation_error(core_client):
    client, _ = core_client()
    for ttl in (0, 2.5):
        response = client.post(URL, json=_body(ttl_s=ttl), headers=OPERATOR)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_no_line_follow_module_imports_or_names_the_advice():
    modules = list((FEATURES / "line_follow").rglob("*.py")) + list((FEATURES / "decision").rglob("*.py"))
    assert FEATURES / "line_follow/authority.py" in modules
    for path in modules:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, (ast.Name, ast.Attribute)):
                names = [getattr(node, "id", None) or node.attr]
            assert not any("advice" in name.lower() for name in names), (path, names)


def _decisions(core_client, advise):
    client, services = core_client()
    clock = {"t": 10.0}
    lf = services.line_follow
    lf.bind_clock(lambda: clock["t"])
    assert client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                      headers=OPERATOR).status_code == 200
    if advise:
        assert client.post(URL, json=_body(), headers=OPERATOR).json()["accepted"] is True
    out = []
    for i in range(10):
        clock["t"] = round(clock["t"] + 0.05, 6)
        lf.observe(LineObservation(LineFollowMode.CAMERA_LINE, clock["t"], True, 0.02 * i, 0.9),
                   received_at=clock["t"])
        decision = lf.tick(clock["t"])
        out.append((decision.linear, decision.angular, lf.status().state, lf.status().reason))
    return out


def test_manager_decisions_are_identical_with_and_without_advice(core_client):
    assert _decisions(core_client, advise=True) == _decisions(core_client, advise=False)
