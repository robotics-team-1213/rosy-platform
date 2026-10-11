"""D-655: survey evidence stays distinct from operational map admission."""

import pytest
from pydantic import ValidationError

from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.site_map import SiteMap


def reference(**changes):
    return {"revision": "survey-1", "origin": [0, 0], "heading_rad": 0,
            "scale_source": "odometry", "description": "Start mark facing east", **changes}


def road(**changes):
    return {"schema": "rosy.site_map/1", "map_id": "new-course",
            "places": [{"id": "a", "name": "start", "x": 0, "y": 0},
                       {"id": "b", "name": "end", "x": 2, "y": 0}],
            "edges": [{"id": "ab", "from": "a", "to": "b", "polyline": [[0, 0], [2, 0]],
                       "width_m": .2, "speed_cap_mps": .03}],
            **changes}


def signal(**changes):
    return {"id": "sig", "name": "Junction light", "kind": "traffic_signal",
            "geometry": [[1, .2]], "signal_id": "sig_ring", "signal_kind": "virtual",
            "approaches": [{"edge_id": "ab", "forward": True, "stop_s_m": .8}], **changes}


def test_empty_survey_roundtrip_and_legacy_body():
    old = SiteMap.model_validate(road()).body()
    assert "survey" not in old and "facilities" not in old and "evidence" not in old["edges"][0]
    empty = SiteMap.model_validate({"places": [], "edges": [], "survey": reference()})
    assert empty.body()["survey"]["reviewed"] is False
    assert SiteMap.model_validate(empty.body()).body() == empty.body()


@pytest.mark.parametrize("changes", [
    {"origin": [float("nan"), 0]}, {"heading_rad": float("inf")},
    {"scale_source": "measured"}, {"measured_distance_m": -1},
    {"reviewed": True}, {"revision": ""}, {"description": " "},
])
def test_bad_survey_reference_is_rejected(changes):
    with pytest.raises(ValidationError):
        SiteMap.model_validate(road(survey=reference(**changes)))


@pytest.mark.parametrize("changes", [
    {"geometry": [[float("inf"), 0]]}, {"geometry": [[0, 0], [1, 1]]},
    {"signal_id": None}, {"signal_kind": None},
    {"approaches": [{"edge_id": "missing", "forward": True}]},
    {"approaches": [{"edge_id": "ab", "forward": True, "stop_s_m": 3}]},
    {"approaches": [{"edge_id": "ab", "forward": True}, {"edge_id": "ab", "forward": True}]},
])
def test_bad_signal_or_lane_relation_is_rejected(changes):
    with pytest.raises(ValidationError):
        SiteMap.model_validate(road(facilities=[signal(**changes)]))


def test_facilities_persist_with_profiles_and_draft(tmp_path):
    path = tmp_path / "maps.sqlite"
    store = SiteMapStore(path)
    map_value = SiteMap.model_validate(road(survey=reference(), facilities=[signal()]))
    draft = store.save_draft(map_value, expected_revision=None, principal_id="operator")
    store.save_profile("survey", name="New course", site_map=map_value,
                       expected_revision=None, principal_id="operator")
    reopened = SiteMapStore(path)
    assert reopened.draft_view()["map"] == draft["map"]
    assert reopened.profiles()[0]["map"]["facilities"][0]["signal_kind"] == "virtual"
    assert reopened.active_view() is None


def test_survey_and_unreviewed_roads_cannot_activate():
    store = SiteMapStore()
    map_value = road(survey=reference())
    saved = store.save_draft(SiteMap.model_validate(map_value), expected_revision=None, principal_id="operator")
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved["revision"], principal_id="operator", route_active=False)
    assert error.value.code == "SITE_MAP_SURVEY_UNREVIEWED"
    map_value["survey"] = reference(reviewed=True, review_note="Origin and metric scale checked")
    map_value["edges"][0]["evidence"] = {
        "source": "odometry", "status": "observed", "reference_revision": "survey-1"}
    saved = store.save_draft(SiteMap.model_validate(map_value), expected_revision=saved["revision"], principal_id="operator")
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved["revision"], principal_id="operator", route_active=False)
    assert error.value.code == "SITE_MAP_ROAD_UNREVIEWED"
    map_value["edges"][0]["evidence"].update(status="reviewed", note="Road inspected")
    saved = store.save_draft(SiteMap.model_validate(map_value), expected_revision=saved["revision"], principal_id="operator")
    assert store.activate(expected_revision=saved["revision"], principal_id="operator", route_active=False)["version"] == 1


def test_mismatched_evidence_revision_is_rejected():
    value = road(survey=reference())
    value["edges"][0]["evidence"] = {"source": "camera", "status": "observed", "reference_revision": "other"}
    with pytest.raises(ValidationError):
        SiteMap.model_validate(value)


def test_exclusion_lane_overlap_blocks_activation():
    store = SiteMapStore()
    facility = {"id": "no-entry", "name": "Keep out", "kind": "exclusion",
                "geometry": [[.5, -.2], [1, -.2], [1, .2], [.5, .2]]}
    saved = store.save_draft(SiteMap.model_validate(road(facilities=[facility])),
                             expected_revision=None, principal_id="operator")
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved["revision"], principal_id="operator", route_active=False)
    assert error.value.code == "SITE_MAP_EXCLUSION_OVERLAP"
    assert store.active_view() is None


def test_valid_polygon_and_duplicate_ids_or_reverse_one_way_relation():
    facility = {"id": "x", "name": "Keep out", "kind": "exclusion",
                "geometry": [[0, 1], [1, 1], [1, 2], [0, 2]]}
    assert SiteMap.model_validate(road(facilities=[facility])).facilities[0].kind == "exclusion"
    for facilities in ([signal(), signal()], [signal(approaches=[{"edge_id": "ab", "forward": False}])]):
        with pytest.raises(ValidationError):
            SiteMap.model_validate(road(facilities=facilities))


@pytest.mark.parametrize("facility", [
    {"id": "x", "name": "line", "kind": "stop_line", "geometry": [[0, 0], [0, 0]]},
    {"id": "x", "name": "zone", "kind": "exclusion", "geometry": [[0, 0], [1, 0], [2, 0]]},
    {"id": "x", "name": "mark", "kind": "landmark", "geometry": [[0, 0]], "signal_kind": "physical"},
])
def test_wrong_facility_geometry_or_device_metadata_is_rejected(facility):
    with pytest.raises(ValidationError):
        SiteMap.model_validate(road(facilities=[facility]))
