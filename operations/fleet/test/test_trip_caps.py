"""D-491 1: Fleet reads a robot's trip caps from its capabilities and plans within them."""

from __future__ import annotations

import pytest

from fleet.server.console_view import TripCaps, trip_caps
from test_site_map_trip import OPERATOR, _app, _on_ring_s


def _caps(**base) -> dict:
    item = {"id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.15,
            "max_angular": 0.6, "pivot": True, "fine": True, "autonomy": ["line"],
            "robot_kind": "pinky_pro", "drive_modes": ["lane"], "trip_max_linear": 0.1, **base}
    return {"navigation": {"goal_navigation": False},
            "controls": {"schema": "rosy.controls/1", "items": [item]}}


def test_trip_caps_reads_the_base_and_ignores_unknown_fields():
    assert trip_caps(_caps(future_field=1)) == TripCaps("pinky_pro", frozenset({"lane"}), 0.1)
    old = _caps()
    for key in ("robot_kind", "drive_modes", "trip_max_linear"):
        del old["controls"]["items"][0][key]
    assert trip_caps(old) is None                      # older image
    for bad in ({"drive_modes": ["fly"]}, {"trip_max_linear": -1}, {"trip_max_linear": True},
                {"robot_kind": ""}, {"drive_modes": "lane"}):
        assert trip_caps(_caps(**bad)) is None
    assert trip_caps(None) is None and trip_caps({"controls": {"items": "x"}}) is None


def _robot_caps(robot, caps):
    async def capabilities():
        return caps
    robot.capabilities = capabilities


def test_plan_honors_drive_modes_and_trip_speed(tmp_path):
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    preview = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert preview.status_code == 200, preview.text          # no caps: preview as before

    (tmp_path / "lane").mkdir()
    client, _tasks, store, robot = _app(tmp_path / "lane")
    robot._state = _on_ring_s(store)
    _robot_caps(robot, _caps(trip_max_linear=0.05))
    slow = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert slow.status_code == 200, slow.text
    assert slow.json()["length_m"] == pytest.approx(preview.json()["length_m"])
    assert slow.json()["eta_s"] > preview.json()["eta_s"]     # 0.05 m/s under the 0.2 lane cap

    for n, refused in enumerate((_caps(drive_modes=["free"]), _caps(trip_max_linear=0.0))):
        (tmp_path / f"refused{n}").mkdir()
        client, _tasks, store, robot = _app(tmp_path / f"refused{n}")
        robot._state = _on_ring_s(store)
        _robot_caps(robot, refused)
        response = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
        assert response.status_code == 422 and response.json()["detail"]["code"] == "TRIP_NO_ROUTE"
