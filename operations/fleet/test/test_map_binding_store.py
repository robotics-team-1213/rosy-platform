"""D-1022 binding store: refit on approval, one active row per robot, history, and the matching rule."""
import math

import pytest

from fleet.localization.map_binding import BindingError, Fit
from fleet.server.site_map_store import SiteMapStore

TRUTH = Fit(math.radians(-20), 0.3, 0.1, ())
SITE = [(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45), (-0.6, 0.4)]
GRID = "occupancy:abcdef012345"


def pairs(points):
    return [{"site": list(p), "robot": list(TRUTH.inverse(p))} for p in points]


def state(grid=GRID, loc="LOCALIZED", frame="map"):
    return {"map_id": "world_261026", "map_grid_id": grid, "localization": {"state": loc, "pose_frame": frame}}


@pytest.fixture
def bindings():
    return SiteMapStore().map_bindings


def test_approval_refits_and_records_the_loaded_grid(bindings):
    row = bindings.approve("rosy_42", state(), ("world_261026", 7), pairs(SITE), pairs([(0, 0)]), "op")
    assert row["robot_grid_id"] == GRID and row["site_map_version"] == 7
    assert row["fit"]["yaw"] == pytest.approx(TRUTH.yaw) and row["fit"]["residual_max_m"] < 1e-9
    fit, reason = bindings.matching_fit("rosy_42", state(), ("world_261026", 7))
    assert reason == "" and fit.apply(TRUTH.inverse((0.5, 0.2))) == pytest.approx((0.5, 0.2))


@pytest.mark.parametrize("bad, code", [
    (state(loc="LOST"), "ROBOT_NOT_LOCALIZED"),
    (state(frame="odom"), "ROBOT_NOT_LOCALIZED"),
    (state(grid=None), "NO_GRID_ID"),
])
def test_approval_needs_a_localized_robot_on_a_loaded_grid(bindings, bad, code):
    with pytest.raises(BindingError) as err:
        bindings.approve("rosy_42", bad, ("world_261026", 7), pairs(SITE), pairs([(0, 0)]), "op")
    assert err.value.code == code
    assert bindings.active("rosy_42") is None


def test_bad_points_are_refused(bindings):
    with pytest.raises(BindingError) as err:
        bindings.approve("rosy_42", state(), ("world_261026", 7),
                         [{"site": [0, 0], "robot": [float("nan"), 0]}] * 3, pairs([(0, 0)]), "op")
    assert err.value.code == "BAD_POINTS"


@pytest.mark.parametrize("probe, site, reason", [
    (state(grid="occupancy:000000000000"), ("world_261026", 7), "MAP_BINDING_GRID_CHANGED"),
    (state(), ("world_261026", 8), "MAP_BINDING_SITE_CHANGED"),
    (state(), None, "MAP_BINDING_SITE_CHANGED"),
    (state(loc="LOST"), ("world_261026", 7), "ROBOT_NOT_LOCALIZED"),
])
def test_a_binding_only_matches_its_grid_site_version_and_a_localized_robot(bindings, probe, site, reason):
    bindings.approve("rosy_42", state(), ("world_261026", 7), pairs(SITE), pairs([(0, 0)]), "op")
    assert bindings.matching_fit("rosy_42", probe, site) == (None, reason)


def test_no_binding_is_required_and_a_new_approval_supersedes_with_history(bindings):
    assert bindings.matching_fit("rosy_42", state(), ("world_261026", 7)) == (None, "MAP_BINDING_REQUIRED")
    first = bindings.approve("rosy_42", state(), ("world_261026", 7), pairs(SITE), pairs([(0, 0)]), "op")
    second = bindings.approve("rosy_42", state(), ("world_261026", 7), pairs(SITE), pairs([(0, 0)]), "op2")
    assert bindings.active("rosy_42")["binding_id"] == second["binding_id"] != first["binding_id"]
    history = bindings.history("rosy_42")
    assert [h["revoke_reason"] for h in history] == [None, "superseded"]
    assert bindings.revoke("rosy_42", "op3", "map re-saved") and bindings.active("rosy_42") is None
    assert bindings.revoke("rosy_42", "op3") is False


def test_a_holdout_that_repeats_a_fit_point_is_refused(bindings):
    with pytest.raises(BindingError) as err:
        bindings.approve("rosy_42", state(), ("world_261026", 7), pairs(SITE), pairs([SITE[0]]), "op")
    assert err.value.code == "BAD_POINTS"
