"""A double-encoded place name is refused at the site map write boundary (TEXT_DOUBLE_ENCODED)."""

import pytest

from fleet.server.sitemap.site_map_store import SiteMapError, SiteMapStore
from fleet.site_map import from_lane_graph
from test_site_map_trip import LANE_GRAPH


def _mangle(text: str) -> str:
    return "".join(chr(b) if b in (0x81, 0x8D, 0x8F, 0x90, 0x9D) else bytes([b]).decode("cp1252")
                   for b in text.encode("utf-8"))


def _named(name: str):
    body = from_lane_graph(LANE_GRAPH).body()
    body["places"][0]["name"] = name
    from fleet.site_map import SiteMap
    return SiteMap.model_validate(body)


def test_draft_and_profile_refuse_double_encoded_names(tmp_path):
    store = SiteMapStore(tmp_path / "sm.db")
    bad = _named(_mangle("상단"))
    with pytest.raises(SiteMapError) as draft:
        store.save_draft(bad, expected_revision=None, principal_id="op")
    assert (draft.value.status_code, draft.value.code) == (400, "TEXT_DOUBLE_ENCODED")
    assert "places.0.name" in str(draft.value)
    with pytest.raises(SiteMapError) as profile:
        store.save_profile("p1", name="x", site_map=bad, expected_revision=None, principal_id="op")
    assert profile.value.code == "TEXT_DOUBLE_ENCODED"
    with pytest.raises(SiteMapError) as title:
        store.save_profile("p1", name=_mangle("가로"), site_map=_named("상단"), expected_revision=None, principal_id="op")
    assert "name" in str(title.value)


def test_valid_korean_name_is_saved(tmp_path):
    store = SiteMapStore(tmp_path / "sm.db")
    assert store.save_draft(_named("상단"), expected_revision=None, principal_id="op")["revision"]
