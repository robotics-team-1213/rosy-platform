import math

import pytest

from fleet.localization.peer_lidar_replay import compare


def observation(robot, x, clusters):
    return dict(robot_id=robot, state="LOCALIZED", stationary=True, grid_id="native", pose_frame="map",
                native_pose=[x, 0, math.pi / 2], scan_stamp=10.05, pose_stamp=10.05, clusters_base_xy=clusters)


def scene():
    return dict(target=dict(robot_id="46", grid_id="native", native_xy=[0, 1], stamp=10.0, stationary=True),
                observers=[observation("42", 0, [[1, 0]]), observation("45", .3, [[1.02, .3]])],
                known_exclusions_xy=[])


def test_two_independent_returns_project_into_one_native_grid():
    result = compare(scene())
    assert result["observer_spread_m"] == pytest.approx(.02)
    assert result["observers"]["45"]["candidate_gap_m"] == pytest.approx(.02)


@pytest.mark.parametrize("change,reason", [
    ({"grid_id": "site"}, "untrusted_or_different_grid"),
    ({"state": "CANDIDATES"}, "untrusted_or_different_grid"),
    ({"pose_stamp": 9.0}, "out_of_capture_window"),
    ({"stationary": False}, "observer_moving"),
    ({"clusters_base_xy": [[1, 0], [.97, .02]]}, "ambiguous"),
])
def test_invalid_or_ambiguous_observer_cannot_support_comparison(change, reason):
    snap = scene()
    snap["observers"][0].update(change)
    result = compare(snap)
    assert result["observers"]["42"]["status"] == reason
    assert result["observer_spread_m"] is None


def test_exclusions_and_duplicate_observers():
    snap = scene()
    snap["known_exclusions_xy"].append([0, 1])
    assert all(row["status"] == "no_return" for row in compare(snap)["observers"].values())
    snap["observers"].append(snap["observers"][0])
    with pytest.raises(ValueError, match="distinct"):
        compare(snap)
