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


class _Leases(dict):
    def __init__(self, leases=(), pending=None):
        super().__init__(leases)
        self.pending = pending or {}


def _run(peer_xy, *, peer_caps=PINKY_CAPS, fit_error=.037, peer_shift=.001, peer_state=None, claims=None, pending=None,
         leases=None, goals=None, own=None):
    fit = Fit(0., 0., 0., (fit_error,))
    # A different transform for the peer by default (its error counts); peer_shift=0 shares the mover's.
    fits = {"mover": fit, "peer": Fit(0., peer_shift, 0., (fit_error,))}
    clients = {"mover": NS(), "peer": NS()}
    kept = {"mover": PINKY_CAPS, "peer": peer_caps}
    console = NS(clients=lambda: clients, robot_ids=clients.keys(), _clearance_m=.7,
                 goal_leases=_Leases(leases if leases is not None else {"peer": {"state": "leased"}}, pending),
                 _goal_busy=set(), _site_claims=claims or {},
                 _claims=own if own is not None else {"peer": [(-1.0, -.55), (.8, -.21)]},
                 _goals=goals if goals is not None else {"peer": {"x": .8, "y": -.21, "yaw": 0.}},
                 _named_stop_site_maps=NS(map_bindings=NS(matching_fit=lambda robot, *_: (fits[robot], None))),
                 _capability_display=NS(_kept=lambda robot, _client: kept[robot]))
    # C1-like bay entry: from P1 (y .04) to staging (y .15) then reversing to the seat (y .47).
    mover = _state(-.42, .04)
    peers = ({"peer": clients["peer"]}, {"peer": _state(*peer_xy) | (peer_state or {})})
    site_corridor(console, "mover", mover, {"site_map_id": "m", "site_map_version": 1}, None, (-.42, .47),
                  peers, route=[(-.42, .15)])


def test_peer_off_centre_shares_the_binding_and_does_not_block():
    # Same grid, same transform: 0.208 m from the entry lane (2.6 cm off its bay centre) clears 0.139 m.
    _run((-.42 + .208, .47), peer_shift=0.)


def test_peer_parked_in_the_neighbour_bay_does_not_block():
    _run((-.42 + .226, .47))                    # C2 centre next to C1


def test_peer_parked_two_bays_away_does_not_block():
    _run((-.42 + .452, .47))


def test_peer_just_outside_the_turn_keep_out_does_not_block():
    # 0.25 m from the staging turn: inside the old 0.288 (both trays), outside 0.23 (user decision 2026-11-27).
    _run((-.42 + .25, .15), peer_shift=0.)


@pytest.mark.parametrize("peer_xy, caps", [
    ((-.42 + .165, .47), PINKY_CAPS),            # off-centre towards the entry lane: bodies plus binding errors overlap
    ((-.42 + .20, .15), PINKY_CAPS),             # beside the staging turn
    ((-.42 + .26, .15 + .02), PINKY_CAPS),       # clear of the body circle but inside the tray's turn sweep
    ((-.42 + .30, .15), PINKY_CAPS),             # 0.30 m: outside 0.23 alone, inside 0.23 plus both binding errors
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


DRIVING = {"mode": "NAVIGATION", "navigation": "NAVIGATING", "velocity": {"linear": .06, "angular": .27}}
# Bottom loop towards the cell: 0.59 m from P1, past 0.288 + 0.074 (binding errors) + 0.1 m/s x 2 s = 0.562 m.
LOOP_CLAIM = ("m", [(-1.0, -.55), (.16, -.55), (.8, -.21)])


def test_peer_driving_a_claimed_route_far_from_the_bay_does_not_block():
    # 2026-11-27: rosy_42 waited at bay 2 staging while rosy_46 drove the bottom loop about 0.6 m away.
    _run((-1.0, -.5), peer_state=DRIVING, claims={"peer": LOOP_CLAIM})


def test_peer_left_in_navigation_mode_after_a_cancel_does_not_block_when_stopped():
    _run((.30, -.29), peer_state={"mode": "NAVIGATION", "navigation": "CANCELED"})


@pytest.mark.parametrize("peer_xy, claims, state, code", [
    ((-1.0, -.33), {}, DRIVING, "PEER_MOTION_UNVERIFIED"),                                  # no Fleet claim
    ((-1.0, -.33), {"peer": ("other", LOOP_CLAIM[1])}, DRIVING, "PEER_MOTION_UNVERIFIED"),  # claim in another map
    ((-1.0, -.33), {"peer": ("m", [(-1.0, -.33), (-.42, .0)])}, DRIVING, "ROUTE_OCCUPIED"),  # route ends at P1
    ((-.42, -.2), {"peer": ("m", [(-.42, -.2), *LOOP_CLAIM[1][1:]])}, DRIVING, "ROUTE_OCCUPIED"),  # 0.24 m from P1
    ((-1.0, -.30), {"peer": LOOP_CLAIM}, DRIVING, "PEER_MOTION_UNVERIFIED"),   # 0.25 m off its claimed route
    ((-1.0, -.5), {"peer": LOOP_CLAIM}, DRIVING | {"mode": "MANUAL"}, "PEER_MOTION_UNVERIFIED"),
    ((-1.0, -.5), {"peer": LOOP_CLAIM}, DRIVING | {"line_follow": {"mode": "LANE"}}, "PEER_MOTION_UNVERIFIED"),
    ((-1.0, -.5), {"peer": LOOP_CLAIM},
     DRIVING | {"evidence": {"pose": {"evidence": "stale"}, "velocity": {"evidence": "fresh"}}}, "PEER_MOTION_UNVERIFIED"),
])
def test_moving_peer_without_a_far_claimed_route_blocks(peer_xy, claims, state, code):
    with pytest.raises(HubError, match="LINE_HANDOFF_" + code):
        _run(peer_xy, peer_state=state, claims=claims)


def test_moving_peer_of_unknown_kind_or_with_a_goal_on_the_wire_blocks():
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _run((-1.0, -.5), peer_state=DRIVING, claims={"peer": LOOP_CLAIM}, peer_caps=None)
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _run((-1.0, -.5), peer_state=DRIVING, claims={"peer": LOOP_CLAIM}, pending={"peer": 1})


@pytest.mark.parametrize("kw", [
    {"leases": {}},                                                  # no Fleet lease: not Fleet's goal
    {"leases": {"peer": {"state": "unbounded"}}},
    {"goals": {}},
    {"goals": {"peer": {"x": .16, "y": -.55, "yaw": 0.}}},           # the claim was written for an older goal
    {"own": {}},
])
def test_moving_peer_claim_must_belong_to_its_leased_goal(kw):
    with pytest.raises(HubError, match="LINE_HANDOFF_PEER_MOTION_UNVERIFIED"):
        _run((-1.0, -.5), peer_state=DRIVING, claims={"peer": LOOP_CLAIM}, **kw)
