"""One keep-out between aligned robots (safety-distance verdict, user decision 2026-11-27)."""
from fleet.localization import trust
from fleet.server import bays
from fleet.server.console import FleetConsole
from fleet.traffic.config import DEFAULT_SITE_KEEP_OUT_M, HEADING_UNKNOWN_KEEP_OUT_M, MIN_SITE_KEEP_OUT_M


def test_every_aligned_keep_out_reads_the_one_value():
    assert DEFAULT_SITE_KEEP_OUT_M == 0.18 and MIN_SITE_KEEP_OUT_M == 0.16
    assert bays.YIELD_KEEP_OUT_M == DEFAULT_SITE_KEEP_OUT_M
    console = FleetConsole([], [])
    assert console._yield_keep_out_m == console._site_keep_out_m == console._goal_blocked_m == DEFAULT_SITE_KEEP_OUT_M


def test_a_robot_of_unknown_heading_keeps_its_circumscribed_body_clear():
    body, mover_half, loc_error = 0.092, 0.07, 0.02
    assert trust.UNTRUSTED_KEEP_OUT_M == HEADING_UNKNOWN_KEEP_OUT_M == 0.20
    assert HEADING_UNKNOWN_KEEP_OUT_M > DEFAULT_SITE_KEEP_OUT_M
    assert abs(HEADING_UNKNOWN_KEEP_OUT_M - (body + mover_half + 2 * loc_error)) < 0.005


def test_the_goal_occupied_distance_follows_the_site_keep_out():
    assert FleetConsole([], [], site_keep_out_m=0.16)._goal_blocked_m == 0.16


def test_the_robot_radius_is_the_circumscribed_body():
    assert bays.ROBOT_RADIUS_M == 0.093   # 0.12 m square + 0.01 padding: diagonal half 0.092
