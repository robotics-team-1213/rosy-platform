"""D-573 6 amendment: the along-track crosswalk error is stated only when enabled, on every frame."""
from control.sensing.perception.camera_ground import ground_plane
from control.sensing.perception.lane_containment import containment_payload, crosswalk_along_uncertainty_m

G = ground_plane(0.0575, 0.19548, 281.6, 160.0, 120.0, 0.6)
ERROR = (0.00436, 0.005, 0.047, 3.0)


def test_along_track_bound_matches_the_measured_table():
    assert abs(crosswalk_along_uncertainty_m(G, ERROR, 0.16) - 0.0215) < 0.001
    assert abs(crosswalk_along_uncertainty_m(G, ERROR, 0.33) - 0.058) < 0.002
    assert crosswalk_along_uncertainty_m(G, None, 0.2) is None


def test_payload_carries_it_only_when_enabled():
    keeper = {"boundaries": [], "crosswalk": (0.15, 0.25)}
    off = containment_payload(keeper, G, stamp=1.0, source="NOMINAL", camera_x=0.033, geometry_bounds=ERROR)
    on = containment_payload(keeper, G, stamp=1.0, source="NOMINAL", camera_x=0.033, geometry_bounds=ERROR,
                             crosswalk_uncertainty=True)
    assert "crosswalk_uncertainty_m" not in off and 0.02 < on["crosswalk_uncertainty_m"] < 0.04
    none = containment_payload({"boundaries": []}, G, stamp=1.0, source="NOMINAL", camera_x=0.033,
                               geometry_bounds=ERROR, crosswalk_uncertainty=True)
    assert none["crosswalk_uncertainty_m"] > 0 and "crosswalk" not in none
