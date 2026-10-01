"""D-395: the global search exposes every refined candidate; global_match keeps its answer."""
import math
from pathlib import Path

import numpy as np

from control.sensing.localization import MapAgreement, apart, valid_beams

FIXTURE = Path(__file__).parent / "fixtures/gazebo_localization_corner.npz"


def recorded():
    d = np.load(FIXTURE)
    return d, MapAgreement(d["grid"], float(d["resolution"]), d["origin"])


def test_valid_beams_drop_nan_short_and_non_finite_angles():
    ranges, angles = valid_beams([1., math.nan, .04, 2., 3.], [0., .1, .2, math.inf, .4])
    assert ranges.tolist() == [1., 3.] and angles.tolist() == [0., .4]


def test_apart_separates_by_position_or_heading_with_wrap():
    assert not apart((0., 0., 0.), (.1, 0., .2))
    assert apart((0., 0., 0.), (.2, 0., 0.))
    assert apart((0., 0., 0.), (0., 0., .4))
    assert not apart((0., 0., math.pi - .1), (0., 0., -math.pi + .1))


def test_clear_poses_keeps_the_footprint_off_walls_and_unknown():
    grid = np.zeros((50, 50), dtype=np.int8)
    grid[:, 40] = 100
    grid[10, 10] = -1
    clear = MapAgreement(grid, .02, (0., 0.)).clear_poses(.1)
    assert clear[25, 25]
    assert not clear[25, 36]      # 8 cm from the wall: inside radius + half a cell
    assert not clear[10, 12]      # unknown is never free


def test_refine_keeps_three_clear_poses_per_seed_around_the_truth():
    d, m = recorded()
    ranges, angles = valid_beams(d["ranges"], d["angles"])
    out = m.refine([np.array(d["truth"])], ranges, angles, m.clear_poses(.105))
    assert len(out) == 3
    best = max(out, key=lambda item: item[0])
    assert math.dist(best[2][:2], d["truth"][:2]) < .02


def test_global_results_are_best_first_and_global_match_reports_the_first():
    d, m = recorded()
    results, reason = m.global_results(d["ranges"], d["angles"], .105)
    assert reason is None and len(results) >= 2
    scores = [r[0] for r in results]
    assert scores == sorted(scores, reverse=True)
    match = m.global_match(d["ranges"], d["angles"], .105)
    assert np.allclose(results[0][2], match["pose"]) and match["unique"]


def test_global_results_name_the_reason_for_an_empty_answer():
    m = MapAgreement(np.zeros((20, 20), dtype=np.int8), .02, (0., 0.))
    assert m.global_results([1.] * 10, np.linspace(-1., 1., 10), .1) == ([], "insufficient-scan")
