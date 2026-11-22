"""2026-11-20: a place or edge a person pinned keeps the flag through the stored map body."""

from __future__ import annotations

from fleet.site_map import SiteMap

MAP = {
    "map_id": "site",
    "places": [{"id": "A", "name": "A", "x": 0.0, "y": 0.0, "pinned": True},
               {"id": "B", "name": "B", "x": 1.0, "y": 0.0}],
    "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0.0, 0.0], [1.0, 0.0]], "width_m": 0.2,
               "speed_cap_mps": 0.2, "pinned": True}],
}


def test_pinned_round_trips_and_an_unpinned_element_stays_byte_equal():
    body = SiteMap.model_validate(MAP).body()
    assert body["places"][0]["pinned"] is True and "pinned" not in body["places"][1]
    assert body["edges"][0]["pinned"] is True
    assert SiteMap.model_validate(body).body() == body
    plain = {**MAP, "places": [{**p, "pinned": False} for p in MAP["places"]],
             "edges": [{k: v for k, v in MAP["edges"][0].items() if k != "pinned"}]}
    assert all("pinned" not in row for row in [*SiteMap.model_validate(plain).body()["places"],
                                               *SiteMap.model_validate(plain).body()["edges"]])
