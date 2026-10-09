"""D-520 step 2: candidate geometry never grants arc motion on its own."""

import math

import pytest

from core_features.line_follow.arc.lane_arc_fit import fit_circle_candidate


RADIUS = 0.3464


def test_fixed_radius_circle_recovers_centre_and_reports_observability():
    points = [(RADIUS * math.cos(math.radians(deg)),
               RADIUS * math.sin(math.radians(deg))) for deg in range(-20, 21, 2)]
    fit = fit_circle_candidate(points, (0.02, -0.01), RADIUS, point_sigma_m=0.002,
                               radial_gate_m=0.06)
    assert fit is not None
    assert math.hypot(*fit.centre_m) < 1e-6
    assert fit.radial_rms_m < 1e-6
    assert fit.span_deg == pytest.approx(40, abs=0.1)
    assert fit.used_points == len(points)
    assert 0 < fit.heading_u95_deg < 5


def test_short_tangent_chord_cannot_claim_a_five_degree_entry():
    # D-520 observability counterexample: these eight straight points satisfy
    # the old 8-point/15-degree/10-mm RMS geometry thresholds.
    points = [(RADIUS, (i - 3.5) * 0.046 / 3.5) for i in range(8)]
    fit = fit_circle_candidate(points, (0.0, 0.0), RADIUS, point_sigma_m=0.010,
                               radial_gate_m=0.06)
    assert fit is not None and fit.radial_rms_m < 0.010
    assert fit.heading_u95_deg > 5


def test_repeated_one_bin_points_have_no_direction_estimate():
    assert fit_circle_candidate([(RADIUS, 0.0)] * 8, (0.0, 0.0), RADIUS,
                                point_sigma_m=0.010, radial_gate_m=0.06) is None


@pytest.mark.parametrize("bad", [0.0, -0.01, math.nan, math.inf])
def test_unbounded_noise_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        fit_circle_candidate([(RADIUS, 0.0)] * 8, (0.0, 0.0), RADIUS,
                             point_sigma_m=bad, radial_gate_m=0.06)
