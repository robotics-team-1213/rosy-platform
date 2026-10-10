"""D-611: learned paint stays until it is late, then the glare fallback holds."""

from control.sensing.perception.evidence_mode import LANE_RETURN_FRAMES, EvidenceModes


def test_an_unarmed_observer_stays_on_the_threshold_and_ignores_a_fresh_model():
    modes = EvidenceModes()
    assert modes.choose_lane(armed=False, model_fresh=True, learned_ok=True, denoise_ok=True) == "threshold"
    assert modes.lane == "threshold"


def test_a_configured_denoise_source_is_named_denoise():
    modes = EvidenceModes()
    assert modes.choose_lane(
        armed=False, model_fresh=False, learned_ok=False, denoise_ok=True, unarmed="denoise") == "denoise"


def test_the_first_fresh_learned_mask_is_the_paint_immediately():
    modes = EvidenceModes()
    assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "learned"


def test_one_late_frame_falls_back_and_one_fresh_frame_does_not_return():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True)
    assert modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True) == "denoise"
    assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "denoise"
    assert modes.lane == "denoise"


def test_learned_paint_returns_only_after_the_hold():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True)
    modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True)
    for _ in range(LANE_RETURN_FRAMES - 1):
        assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "denoise"
    assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "learned"


def test_a_late_frame_during_the_return_hold_starts_the_hold_over():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True)
    modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True)
    assert modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True) == "denoise"
    assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "denoise"


def test_both_sources_missing_is_no_lane():
    modes = EvidenceModes()
    assert modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=False) == "none"


def test_a_reset_takes_the_next_fresh_mask_immediately():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True)
    modes.reset()
    assert modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True) == "learned"


def test_rows_add_a_hold_and_never_treat_the_signal_as_a_go():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=True, learned_ok=True, denoise_ok=True)
    quiet = modes.rows(crosswalk=False, stop_line=True, obstacle=False)
    assert quiet["stop_line"] == "class"
    assert quiet["obstacle"] == "metric"
    assert quiet["signal"] == "hsv"
    assert quiet["crosswalk"] == "none"
    held = modes.rows(crosswalk=True, stop_line=False, obstacle=True)
    assert held["crosswalk"] == "reported"
    assert held["obstacle"] == "hold"
    assert held["stop_line"] == "none"


def test_a_stop_line_class_is_not_reported_from_the_denoise_fallback():
    modes = EvidenceModes()
    modes.choose_lane(armed=True, model_fresh=False, learned_ok=False, denoise_ok=True)
    assert modes.rows(crosswalk=False, stop_line=True, obstacle=False)["stop_line"] == "none"
