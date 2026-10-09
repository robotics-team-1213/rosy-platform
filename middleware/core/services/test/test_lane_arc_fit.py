"""D-520 step 2: candidate geometry never grants arc motion on its own."""

import math

import pytest

from core_features.line_follow.arc.lane_arc_fit import fit_circle_candidate


RADIUS = 0.3464


def test_fixed_radius_circle_recovers_centre_and_reports_observability():
    points = [(RADIUS * math.cos(math.radians(deg)),
               RADIUS + RADIUS * math.sin(math.radians(deg))) for deg in range(-110, -69, 2)]
    fit = fit_circle_candidate(points, (0.02, RADIUS - 0.01), RADIUS, point_sigma_m=0.002,
                               radial_gate_m=0.06)
    assert fit is not None
    assert math.dist(fit.centre_m, (0.0, RADIUS)) < 1e-6
    assert fit.radial_rms_m < 1e-6
    assert fit.span_deg == pytest.approx(40, abs=0.1)
    assert fit.used_points == len(points)
    assert 0 < fit.heading_u95_deg < 5


def test_short_tangent_chord_cannot_claim_a_five_degree_entry():
    # D-520 observability counterexample: these eight straight points satisfy
    # the old 8-point/15-degree/10-mm RMS geometry thresholds.
    points = [((i - 3.5) * 0.046 / 3.5, 0.0) for i in range(8)]
    fit = fit_circle_candidate(points, (0.0, RADIUS), RADIUS, point_sigma_m=0.010,
                               radial_gate_m=0.06)
    assert fit is not None and fit.radial_rms_m < 0.010
    assert fit.heading_u95_deg > 5


def test_slanted_straight_chord_exposes_better_line_explanation():
    points = [((i - 3.5) * 0.046 / 3.5, (i - 3.5) * 0.046 / 3.5 * 0.15)
              for i in range(8)]
    fit = fit_circle_candidate(points, (0.0, RADIUS), RADIUS, point_sigma_m=0.002,
                               radial_gate_m=0.06)
    assert fit is not None
    assert fit.line_rms_m < fit.radial_rms_m


def test_repeating_pixels_does_not_increase_independent_support():
    points = [((i - 3.5) * 0.046 / 3.5, (i - 3.5) * 0.046 / 3.5 * 0.15)
              for i in range(8)]
    once = fit_circle_candidate(points, (0.0, RADIUS), RADIUS, point_sigma_m=0.005,
                                radial_gate_m=0.06)
    repeated = fit_circle_candidate(points * 4, (0.0, RADIUS), RADIUS,
                                    point_sigma_m=0.005, radial_gate_m=0.06)
    assert once is not None and repeated is not None
    assert repeated.used_points == once.used_points
    assert repeated.heading_u95_deg == pytest.approx(once.heading_u95_deg)


def test_radial_spoke_is_not_used_to_move_the_outer_circle():
    arc = [(RADIUS * math.cos(math.radians(deg)),
            RADIUS + RADIUS * math.sin(math.radians(deg))) for deg in range(-110, -69, 2)]
    spoke = [(0.0, i * 0.008) for i in range(-7, 8) if i]
    fit = fit_circle_candidate(arc + spoke, (0.0, RADIUS), RADIUS,
                               point_sigma_m=0.005, radial_gate_m=0.06)
    assert fit is not None
    assert fit.used_points <= len(arc) + 2
    assert math.dist(fit.centre_m, (0.0, RADIUS)) < 0.005


def test_repeated_one_bin_points_have_no_direction_estimate():
    assert fit_circle_candidate([(0.0, 0.0)] * 8, (0.0, RADIUS), RADIUS,
                                point_sigma_m=0.010, radial_gate_m=0.06) is None


@pytest.mark.parametrize("bad", [0.0, -0.01, math.nan, math.inf])
def test_unbounded_noise_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        fit_circle_candidate([(0.0, 0.0)] * 8, (0.0, RADIUS), RADIUS,
                             point_sigma_m=bad, radial_gate_m=0.06)
