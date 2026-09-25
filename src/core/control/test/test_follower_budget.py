"""Per-update time of the junction followers (A, B and the route_ab hybrid H),
closed loop.

CORE's line_follow stale_after_s is 0.3 s and the camera runs at 5 Hz, so
one update must finish well inside a 0.2 s frame; BUDGET_P95_S leaves half
of it. Measured on the Windows dev host over scenarios 00, 05 and 09 (the
first update, which builds the bird's-eye lookup tables, excluded):

  before the lane_bev speedups   A median 65.3 ms, p95 107.8 ms
                                 B median 73.1 ms, p95 110.1 ms
  after                          A median 14.4 ms, p95 22.3 ms
                                 B median 24.1 ms, p95 31.2 ms

The speedups: _LineMemory keeps its cells in numpy arrays (prune was a
per-cell Python loop, 13 ms a call), and _band_lookahead works on the path
cells only, with the view's range and bearing computed once.

H (2026-09-23, the host at 100 % CPU from other work, three runs):
A median 15.8-17.7 ms, p95 37.9-45.9 ms; B 24.7-26.9 / 53.6-61.8 ms;
H 21.7-24.1 / 51.6-85.6 ms. H's parts, one run: localiser median 7.9 ms,
A's follower 14.6 ms, the disagreement check 3.4 ms. Its p95 is the
closest to the budget of the three; re-measure on an idle host.
"""

import time

import numpy as np
import pytest
from control.sensing.perception.route_camera import RouteCameraFollower
from control.sensing.perception.route_hybrid import RouteHybridFollower
from control.sensing.perception.route_map import RouteMapFollower
from lane_scenarios import GRAPH, SCENARIOS, run_scenario
from lane_sim import CAM_X

BUDGET_P95_S = 0.100


class _Timed:
    def __init__(self, subject):
        self.subject = subject
        self.times = []

    @property
    def state(self):
        return self.subject.state

    def update(self, *args, **kwargs):
        t0 = time.perf_counter()
        out = self.subject.update(*args, **kwargs)
        self.times.append(time.perf_counter() - t0)
        return out


def _build(kind, scenario):
    keys = [scenario["into"], scenario["out"]]
    if kind == "A":
        return RouteCameraFollower(GRAPH, keys, start_pose=scenario["start"],
                                   camera_x_offset_m=CAM_X)
    if kind == "B":
        return RouteMapFollower(GRAPH, keys, start_pose=scenario["start"],
                                camera_x_offset_m=CAM_X, seed=7)
    return RouteHybridFollower(GRAPH, keys, start_pose=scenario["start"],
                               camera_x_offset_m=CAM_X, seed=7)


@pytest.mark.parametrize("kind", ["A", "B", "H"])
def test_one_update_fits_the_frame_budget(kind):
    times = []
    for index in (0, 5, 9):
        timed = _Timed(_build(kind, SCENARIOS[index]))
        run_scenario(SCENARIOS[index], timed, steps=260)
        times += timed.times[1:]
    median, p95 = np.median(times), np.percentile(times, 95)
    print(f"\n{kind}: {len(times)} updates, median {median * 1000:.1f} ms, "
          f"p95 {p95 * 1000:.1f} ms, max {max(times) * 1000:.1f} ms")
    assert p95 <= BUDGET_P95_S, (median, p95)
