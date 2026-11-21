"""Normal stopping geometry, without enabling a command or changing trial gates."""
from dataclasses import replace
import math

import numpy as np
import pytest

from core_common.robot_body import NOMINAL_BODY
import control.control.footprint_sweep as sweep


FAR = ((2., 2.), (2., -2.), (-2., 2.))


def judge(points=FAR, **changes):
    arguments = dict(body=NOMINAL_BODY, linear=.08, angular=.4,
                     limits=(.1, .8), previous_limits=(.1, .8),
                     scan_age=.01, source_age=.01, evaluation_budget_s=.01)
    arguments.update(changes)
    return sweep.forward_stopping_sweep_clearance(points, **arguments)


def test_normal_forward_curve_exceeds_trial_domain_without_widening_trial():
    assert judge() > 0.
    hull = ((.05, .05), (.05, -.05), (-.05, -.05), (-.05, .05))
    assert sweep.footprint_sweep_clearance(FAR, hull, (0., 0.), 0.,
        math.sqrt(.005), .08, .4, .8, .01) is None


def test_braking_contact_is_not_judged_only_at_current_body():
    # .095m is initially beyond body + lateral/delay pads, but not the stop path.
    assert judge(((.095, 0.), *FAR), linear=.1, angular=0.,
                 previous_limits=(0., 0.), scan_age=0., source_age=0.) <= 0.


def test_forward_margin_extends_path_instead_of_becoming_a_lateral_pad():
    assert judge(((0., .08), *FAR), linear=.01, angular=0.,
                 previous_limits=(0., 0.), scan_age=0., source_age=0.) > 0.
    assert judge(((.07, 0.), *FAR), linear=.01, angular=0.,
                 previous_limits=(0., 0.), scan_age=0., source_age=0.) <= 0.


def test_old_different_curve_transition_cannot_be_assumed_to_match_new_curve():
    points = ((0., .145), *FAR)
    assert judge(points, linear=.05, angular=0., previous_limits=(0., 0.)) > 0.
    assert judge(points, linear=.05, angular=0., previous_limits=(.1, 8.)) <= 0.


def test_old_heading_rotates_future_braking_path_not_only_current_body():
    # Old in-place rotation can yaw the entire subsequent straight stopping path.
    distance, heading = 1. + NOMINAL_BODY.margin_m, 2. * (.15 + .01)
    point = (distance * math.cos(heading), distance * math.sin(heading))
    reach = math.hypot(-NOMINAL_BODY.rear_x_m, NOMINAL_BODY.half_width_m)
    insufficient_pad = .010 + (1. + 2. * reach) * (.15 + .01)
    assert point[1] - NOMINAL_BODY.half_width_m > insufficient_pad
    assert judge((point, *FAR), linear=1., angular=0., limits=(1., .8),
                 previous_limits=(0., 2.), scan_age=0., source_age=0.) <= 0.


def test_intermediate_contact_when_both_endpoint_footprints_clear():
    # A larger applied profile exercises the continuous-cover math, not runtime admission.
    curvature = .2
    point = (math.sin(.6 * curvature) / curvature,
             (1. - math.cos(.6 * curvature)) / curvature)
    body = NOMINAL_BODY
    hull = sweep._hull(sweep._points(((body.front_x_m, body.half_width_m),
        (body.front_x_m, -body.half_width_m), (body.rear_x_m, -body.half_width_m),
        (body.rear_x_m, body.half_width_m))))
    reach = max(np.linalg.norm(vertex) for vertex in hull)
    travel = 1. + body.margin_m
    pad = body.sweep_pad_m + (1. + curvature * (reach + travel)) * (body.latency_s + .01)
    pad += (1. + curvature * reach) * travel / 128.
    for distance in (0., 1. + body.margin_m):
        angle = distance * curvature
        rotation = np.array(((math.cos(angle), math.sin(angle)),
                             (-math.sin(angle), math.cos(angle))))
        polygon = hull @ rotation + (math.sin(angle) / curvature,
                                     (1. - math.cos(angle)) / curvature)
        assert sweep._clearance(sweep._points((point, *FAR)), polygon) > pad
    assert judge((point, *FAR), linear=1., angular=curvature, limits=(1., 1.),
                 previous_limits=(0., 0.), scan_age=0., source_age=0.) <= 0.


@pytest.mark.parametrize('changes', [dict(linear=0.), dict(linear=-.01),
    dict(linear=float('nan')), dict(angular=float('inf')), dict(limits=None),
    dict(previous_limits=None), dict(limits=(.01, .8)), dict(limits=(.1, -.1)),
    dict(previous_limits=(True, .8)), dict(scan_age=.201), dict(source_age=-.01),
    dict(evaluation_budget_s=-.01), dict(body=None),
    dict(body=replace(NOMINAL_BODY, margin_m=.01)),
    dict(body=replace(NOMINAL_BODY, sweep_pad_m=.005)),
    dict(body=replace(NOMINAL_BODY, latency_s=.1)),
    dict(body=replace(NOMINAL_BODY, decel_mps2=1.))])
def test_missing_or_invalid_normal_contract_refuses(changes):
    assert judge(**changes) is None


@pytest.mark.parametrize('points', [(), ((0., 0.),),
    ((float('nan'), 0.), (1., 1.), (-1., 1.))])
def test_unknown_or_nonfinite_geometry_cannot_be_clear(points):
    assert judge(points) is None
