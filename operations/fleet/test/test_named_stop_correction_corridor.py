import asyncio
import math
from types import SimpleNamespace as NS

import pytest

from fleet.hub.hub import HubError
from fleet.localization.map_binding import Fit
from fleet.server.site_map_store import SiteMapStore
from fleet.server.correction_corridor import check_correction_path
from fleet.site_map import PrecisionStopLimits, SiteMap, SiteWall
from test_trip_runner import _free_map


@pytest.mark.parametrize("case", ["forward", "reverse", "overshoot_narrow", "heading_margin", "peer", "wall", "cable",
                                  "late_cable", "odom_pose", "changed_grid", "changed_stop", "no_terminal"])
def test_correction_checks_the_full_approved_terminal_path(case):
    async def run():
        limits = PrecisionStopLimits(evidence_ref="synthetic", reference_pose=(1., 1., math.pi / 2),
                                     longitudinal_m=.02, lateral_m=.012,
                                     heading_rad=.05, position_uncertainty_m=.002,
                                     heading_uncertainty_rad=.01, max_correction_m=.08)
        original = _free_map()
        model = original.body()
        for place in model["places"]:
            if place["id"] == "C":
                place.update(kind="stop", yaw=math.pi / 2, precision_stop=limits.model_dump())
        model["edges"][1]["width_m"] = .20 if case in ("overshoot_narrow", "heading_margin") else .42
        if case == "wall":
            model["walls"] = [SiteWall(id="close", face=((.92, .985), (1.08, .985))).model_dump()]
        site = SiteMap.model_validate(model)
        maps = SiteMapStore()
        try:
            version = maps.import_if_empty(site, source="test")
            active = maps.active_view()
            fit = Fit(0., 0., 0., (.001,))
            binding = NS(active=lambda _robot: {"binding_id": "fused"}, matching_fit=lambda *_: (fit, None))
            maps.map_bindings = binding
            cable_inhibited = case == "cable"
            token = 0

            def state(x, y):
                return dict(pose=dict(x=x, y=y, yaw=math.pi / 2), mode="IDLE", navigation="ARRIVED",
                            pose_frame="odom" if case == "odom_pose" else "map",
                            localization={"pose_frame": "map"},
                            velocity=dict(linear=0., angular=0.), line_follow={"mode": "OFF"}, map_grid_id="grid",
                            evidence={channel: {"evidence": "fresh"} for channel in ("pose", "velocity")})

            async def own_state():
                nonlocal cable_inhibited, token
                if case == "late_cable":
                    cable_inhibited = True
                if case == "changed_stop":
                    token += 1
                y = 1.04 if case in ("reverse", "overshoot_narrow") else .96
                x = 1.0042 if case == "heading_margin" else 1.
                return {**state(x, y), "map_grid_id": "changed" if case == "changed_grid" else "grid"}

            async def peer_state():
                return state(1., .95) if case == "peer" else state(.2, .2)

            clients = {"pinky": NS(state=own_state), "peer": NS(state=peer_state)}
            leases = NS(pending={}, stop_token=lambda _: token)
            console = NS(clients=lambda: clients, robot_ids=clients.keys(), goal_leases=leases,
                         _named_stop_site_maps=maps, _goal_busy=set(), _clearance_m=.18, _clock=lambda: 0.)
            scope = {"correlation_id": "attempt", "terminal": {"arc_id": "bc:fwd", "s_from": .7, "s_to": 1.,
                                                             "robot_kind": "pinky_pro"}}
            live = NS(open=True, view={"robot_id": "pinky", "detail": {"named_stop_handoff_pending":
                                                                        {} if case == "no_terminal" else scope}})
            evidence = dict(attempt_id="attempt", map_id=site.map_id, map_version=version,
                            map_sha256=active["sha256"], map_grid_id="grid", binding_id="fused")
            place = next(item for item in active["map"]["places"] if item["id"] == "C")
            checked = check_correction_path(console, live, evidence, place, cable_inhibited=lambda _: cable_inhibited)
            if case in ("forward", "reverse"):
                decision = await checked
                assert decision["site_end"] == pytest.approx([1., 1.])
                assert decision["forward_m"] == pytest.approx(.04 if case == "forward" else -.04)
            else:
                reason = {"overshoot_narrow": "PATH_OUTSIDE_TERMINAL", "heading_margin": "PATH_OUTSIDE_TERMINAL",
                          "peer": "ROUTE_OCCUPIED",
                          "wall": "CORRECTION_WALL", "cable": "CABLE_HOLD", "late_cable": "ADMISSION_CHANGED",
                          "changed_grid": "DISPATCH_FRAME_CHANGED", "changed_stop": "ADMISSION_CHANGED",
                          "odom_pose": "CORRECTION_POSE_CHANGED",
                          "no_terminal": "TERMINAL_REQUIRED"}[case]
                with pytest.raises(HubError, match=reason):
                    await checked
        finally:
            maps.close()

    asyncio.run(run())
