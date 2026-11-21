"""2026-11-21 (robot-7b named stop): a stop's drawn stop_zone and approach_m on the site map."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from fleet.site_map import SiteMap, SitePlace, approach_pose

ZONE = [[0.9, -0.1], [1.1, -0.1], [1.1, 0.1], [0.9, 0.1]]


def _map(**stop) -> dict:
    place = {"id": "B", "name": "B", "x": 1.0, "y": 0.0, "kind": "stop", **stop}
    return {"map_id": "site",
            "places": [{"id": "A", "name": "A", "x": 0.0, "y": 0.0}, place],
            "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0.0, 0.0], [1.0, 0.0]],
                       "width_m": 0.2, "speed_cap_mps": 0.2}]}


def test_a_pinned_stop_keeps_its_zone_and_approach_through_the_body():
    body = SiteMap.model_validate(_map(yaw=0.0, pinned=True, stop_zone=ZONE, approach_m=0.3)).body()
    stop = body["places"][1]
    assert stop["stop_zone"] == ZONE and stop["approach_m"] == 0.3
    assert SiteMap.model_validate(body).body() == body


def test_a_map_without_the_fields_stays_byte_equal():
    body = SiteMap.model_validate(_map()).body()
    assert all("stop_zone" not in p and "approach_m" not in p for p in body["places"])
    assert body["places"][1] == {"id": "B", "name": "B", "x": 1.0, "y": 0.0, "yaw": None, "kind": "stop"}


@pytest.mark.parametrize("stop, message", [
    ({"kind": "park", "pinned": True, "stop_zone": ZONE}, "belong to a stop"),
    ({"kind": "junction", "yaw": 0.0, "approach_m": 0.3}, "belong to a stop"),
    ({"pinned": True, "stop_zone": [[1.2, -0.1], [1.4, -0.1], [1.4, 0.1]]}, "outside its stop_zone"),
    ({"stop_zone": ZONE}, "needs pinned"),
    ({"pinned": True, "stop_zone": [[0.9, 0.0], [1.1, 0.0], [1.0, 0.0]]}, "smaller than"),
    ({"pinned": True, "stop_zone": [[0.0, -2.0], [2.0, -2.0], [2.0, 2.0]]}, "spans more than"),
    ({"pinned": True, "stop_zone": [[0.9, -0.1], [math.inf, -0.1], [1.1, 0.1]]}, "finite"),
    ({"pinned": True, "stop_zone": ZONE[:2]}, "at least 3"),
    ({"yaw": 0.0, "approach_m": 0.04}, "greater than or equal"),
    ({"yaw": 0.0, "approach_m": 0.61}, "less than or equal"),
    ({"approach_m": 0.3}, "needs a yaw"),
])
def test_a_bad_stop_zone_or_approach_is_refused(stop, message):
    with pytest.raises(ValidationError, match=message):
        SiteMap.model_validate(_map(**stop))


def test_approach_pose_lies_behind_the_stop_along_its_yaw():
    stop = SitePlace(id="B", name="B", x=1.0, y=2.0, yaw=math.pi / 2, kind="stop", approach_m=0.3)
    x, y, yaw = approach_pose(stop)
    assert (x, y, yaw) == (pytest.approx(1.0), pytest.approx(1.7), math.pi / 2)
    assert approach_pose(SitePlace(id="C", name="C", x=0.0, y=0.0, kind="stop")) is None
