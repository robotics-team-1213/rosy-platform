"""A plain stop place is reached at the stop-line offset; only a precision stop ends on the place xy."""
import asyncio
import math
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from fleet.routing.graph import build_graph
from fleet.routing.stop_line import FALLBACK_FRONT_M, STOP_MARGIN_M
from fleet.server.task_dispatch_helpers import compute_road_plan
from fleet.site_map import SiteMap

S3 = (0.745, 0.2)
PRECISION = dict(evidence_ref="model S top view", reference_pose=(S3[0], S3[1], math.pi), longitudinal_m=0.03,
                 lateral_m=0.03, heading_rad=math.radians(5), position_uncertainty_m=0.008,
                 heading_uncertainty_rad=0.035, max_correction_m=0.05)


def _plan(precision=False):
    s3 = {"id": "S3", "name": "S3", "x": S3[0], "y": S3[1], "kind": "stop", "yaw": math.pi}
    if precision:
        s3.update(pinned=True, precision_stop=PRECISION)
    site = SiteMap(places=[{"id": "A", "name": "A", "x": 1.9, "y": 0.2, "kind": "junction"}, s3],
                   edges=[{"id": "as", "from": "A", "to": "S3", "polyline": [[1.9, 0.2], list(S3)],
                           "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 1.0}])
    graph = build_graph(site, version=1)
    frames = SimpleNamespace(bind=lambda *_: ((1.5, 0.2, math.pi), {"binding_id": "fit-1"}, None),
                             to_nav2=lambda pose, *_: pose)
    maps = SimpleNamespace(active=lambda: (1, SimpleNamespace(map_id="cell"), graph))
    state = {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "localization": {"state": "LOCALIZED", "pose_frame": "map"}}

    async def snap():
        return {"robots": [{"robot_id": "rosy_46", "state": state}]}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(site_maps=maps, named_stop_frame=frames)))
    return asyncio.run(compute_road_plan(SimpleNamespace(snapshot=snap), request, "rosy_46", 0.0, 0.0, None, "S3", ""))


def test_plain_stop_is_planned_and_ends_at_the_stop_line_offset():
    out = _plan()
    x = S3[0] + FALLBACK_FRONT_M + STOP_MARGIN_M
    assert math.isclose(out["waypoints_site"][-1]["x"], x, abs_tol=1e-3)
    assert math.isclose(out["target_site"]["x"], x, abs_tol=1e-3) and out["target_site"]["place_id"] == "S3"
    assert math.isclose(out["target_nav2"]["x"], x, abs_tol=1e-3)


def test_precision_stop_keeps_the_strict_place_endpoint():
    # stop_goals is empty for a precision stop, so the route ends on the place and the strict check holds.
    out = _plan(precision=True)
    assert math.isclose(out["waypoints_site"][-1]["x"], S3[0], abs_tol=1e-3)
    assert math.isclose(out["target_site"]["x"], S3[0], abs_tol=1e-3)
