"""A stopped, bound peer parked in a neighbouring bay does not block a rear-bay entry (body geometry)."""
import math
from types import SimpleNamespace as NS

import pytest

from fleet.hub.hub import HubError
from fleet.localization.map_binding import Fit
from fleet.server.handoff_traffic import site_corridor

PINKY_CAPS = {"controls": {"items": [{"kind": "base_velocity", "robot_kind": "pinky_pro",
                                      "drive_modes": ["free"], "trip_max_linear": .1}]}}


def _state(x, y):
    return dict(pose=dict(x=x, y=y, yaw=-math.pi / 2), mode="IDLE", navigation="ARRIVED",
                velocity=dict(linear=0., angular=0.), line_follow={"mode": "OFF"}, map_grid_id="grid",
                evidence={channel: {"evidence": "fresh"} for channel in ("pose", "velocity")})


def _run(peer_xy, *, peer_caps=PINKY_CAPS, fit_error=.037, peer_shift=.001):
    fit = Fit(0., 0., 0., (fit_error,))
    # A different transform for the peer by default (its error counts); peer_shift=0 shares the mover's.
    fits = {"mover": fit, "peer": Fit(0., peer_shift, 0., (fit_error,))}
    clients = {"mover": NS(), "peer": NS()}
    kept = {"mover": PINKY_CAPS, "peer": peer_caps}
    console = NS(clients=lambda: clients, robot_ids=clients.keys(), _clearance_m=.7,
                 goal_leases=NS(pending={}), _goal_busy=set(),
                 _named_stop_site_maps=NS(map_bindings=NS(matching_fit=lambda robot, *_: (fits[robot], None))),
                 _capability_display=NS(_kept=lambda robot, _client: kept[robot]))
    # C1-like bay entry: from P1 (y .04) to staging (y .15) then reversing to the seat (y .47).
    mover = _state(-.42, .04)
    peers = ({"peer": clients["peer"]}, {"peer": _state(*peer_xy)})
    site_corridor(console, "mover", mover, {"site_map_id": "m", "site_map_version": 1}, None, (-.42, .47),
                  peers, route=[(-.42, .15)])


def test_peer_off_centre_shares_the_binding_and_does_not_block():
    # Same grid, same transform: 0.208 m from the entry lane (2.6 cm off its bay centre) clears 0.139 m.
    _run((-.42 + .208, .47), peer_shift=0.)


def test_peer_parked_in_the_neighbour_bay_does_not_block():
    _run((-.42 + .226, .47))                    # C2 centre next to C1


def test_peer_parked_two_bays_away_does_not_block():
    _run((-.42 + .452, .47))


@pytest.mark.parametrize("peer_xy, caps", [
    ((-.42 + .165, .47), PINKY_CAPS),            # off-centre towards the entry lane: bodies plus binding errors overlap
    ((-.42 + .20, .15), PINKY_CAPS),             # beside the staging turn
    ((-.42 + .26, .15 + .02), PINKY_CAPS),       # clear of the body circle but inside the tray's turn sweep
    ((-.42 + .45, .47), None),                   # unknown kind keeps the general 0.7 m clearance
])
def test_peer_too_close_or_of_unknown_geometry_blocks(peer_xy, caps):
    with pytest.raises(HubError, match="LINE_HANDOFF_ROUTE_OCCUPIED"):
        _run(peer_xy, peer_caps=caps)


def test_stopped_deadband_and_offline_absent_peer_do_not_block():
    from fleet.server.handoff_traffic import _fresh_stopped, read_peers
    jitter = _state(-.42 + .226, .47) | {"velocity": {"linear": 0.005, "angular": -0.015}}
    assert _fresh_stopped(jitter) is True
    # Offline peer cleared by OfflineMarkerClearance does not block bay handoff.
    fit = Fit(0., 0., 0., (.037,))
    clients = {"mover": NS(state=lambda: asyncio.sleep(0, _state(-.42, .04)))}
    async def dead():
        raise OSError("offline")
    all_clients = {**clients, "peer": NS(state=dead)}
    clearance = NS(clear=lambda *_a: True, evidence=lambda *_a: {"reason": "peer_absent_from_track"})
    console = NS(clients=lambda: all_clients, robot_ids=("mover", "peer"), _clearance_m=.7,
                 goal_leases=NS(pending={}), _goal_busy=set(), _site_marker_clearance=clearance,
                 _named_stop_site_maps=NS(map_bindings=NS(matching_fit=lambda *_a: (fit, None))),
                 _capability_display=NS(_kept=lambda *_a: PINKY_CAPS))
    import asyncio
    peers = asyncio.run(read_peers(console, "mover"))
    site_corridor(console, "mover", _state(-.42, .04), {"site_map_id": "m", "site_map_version": 1},
                  None, (-.42, .47), peers, route=[(-.42, .15)])
    clearance.clear = lambda *_a: False
    clearance.evidence = lambda *_a: {"reason": "keep_out_intersection"}
    with pytest.raises(HubError, match="LINE_HANDOFF_ROUTE_OCCUPIED"):
        site_corridor(console, "mover", _state(-.42, .04), {"site_map_id": "m", "site_map_version": 1},
                      None, (-.42, .47), peers, route=[(-.42, .15)])


def _peer_run(peer_state, **kw):
    fit = Fit(0., 0., 0., (.037,))
    clients = {"mover": NS(), "peer": NS()}
    console = NS(clients=lambda: clients, robot_ids=clients.keys(), _clearance_m=.7,
                 goal_leases=NS(pending={}), _goal_busy=set(),
                 _named_stop_site_maps=NS(map_bindings=NS(matching_fit=lambda *_a: (fit, None))),
                 _capability_display=NS(_kept=lambda *_a: PINKY_CAPS))
    site_corridor(console, "mover", _state(-.42, .04), {"site_map_id": "m", "site_map_version": 1}, None, (-.42, .47),
                  ({"peer": clients["peer"]}, {"peer": peer_state}), route=[(-.42, .15)], **kw)


def test_navigation_mode_peer_waits_unless_fleet_holds_it_for_the_mover():
    sticky = _state(-.42 + .452, .47) | {"mode": "NAVIGATION", "navigation": "IDLE"}
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _peer_run(sticky)
    _peer_run(sticky, held_by_fleet={"peer"})
    # Still a fixed body: geometry applies, and a moving or goal-active held peer is not accepted.
    with pytest.raises(HubError, match="LINE_HANDOFF_ROUTE_OCCUPIED"):
        _peer_run(_state(-.42 + .10, .47) | {"mode": "NAVIGATION"}, held_by_fleet={"peer"})
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _peer_run(sticky | {"navigation": "NAVIGATING"}, held_by_fleet={"peer"})
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _peer_run(sticky | {"velocity": {"linear": .1, "angular": 0.}}, held_by_fleet={"peer"})
