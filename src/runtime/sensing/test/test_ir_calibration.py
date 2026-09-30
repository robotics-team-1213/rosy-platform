"""D-344 §12: IR line calibration from placed-robot samples (pure part of the device tool)."""

import json
import random

import pytest

from control.sensing.perception.ir_calibration import (
    channel_levels, compute_ir_calibration, ir_side, render_config, sign_errors)
from control.sensing.perception.lane import IRLineCalibration
from tools.device import ir_line_calibrate as tool

CARPET = (1200.0, 1150.0, 1250.0)
TAPE = (3100.0, 3000.0, 3200.0)


def _samples(levels, n=60, noise=15.0, seed=1, outliers=0):
    rng = random.Random(seed)
    rows = [[round(level + rng.gauss(0.0, noise)) for level in levels] for _ in range(n)]
    for index in range(outliers):
        rows[index] = [4095, 0, 9]      # rail + junk reads
    return rows


def _session(carpet=CARPET, tape=TAPE, **kwargs):
    def phase(which):
        return tuple(tape[i] if i == which else carpet[i] for i in range(3))
    return {
        "carpet": _samples(carpet, seed=1, **kwargs),
        "left": _samples(phase(0), seed=2, **kwargs),
        "centre": _samples(phase(1), seed=3, **kwargs),
        "right": _samples(phase(2), seed=4, **kwargs),
    }


def test_endpoints_are_robust_medians_and_match_the_observer_digest():
    result = compute_ir_calibration(_session(outliers=3))
    assert result.ok, result.errors
    for got, want in zip(result.black, CARPET):
        assert got == pytest.approx(want, abs=10)
    for got, want in zip(result.white, TAPE):
        assert got == pytest.approx(want, abs=10)
    # line_observer_node builds the calibration from the same floats -> same digest
    node_side = IRLineCalibration(black=tuple(float(v) for v in result.black),
                                  white=tuple(float(v) for v in result.white), min_span=100.0)
    assert result.revision == node_side.revision
    assert ir_side(result.phase_errors["left"]) == "left"
    assert ir_side(result.phase_errors["right"]) == "right"
    assert ir_side(result.phase_errors["centre"]) == "centre"
    assert result.phase_errors["carpet"] is None


def test_rendered_yaml_is_float_typed_and_carries_the_core_revision():
    yaml = pytest.importorskip("yaml")
    result = compute_ir_calibration(_session())
    text = render_config(result)
    blocks = text.split("\n\n")
    observer = yaml.safe_load(blocks[0])["/**/line_observer_node"]["ros__parameters"]
    assert observer["ir_calibration_enabled"] is True
    assert all(isinstance(v, float) for v in observer["ir_black"] + observer["ir_white"])
    assert yaml.safe_load(blocks[1])["line_follow"]["ir_calibration_revision"] == result.revision


def test_inverted_polarity_hardware_is_accepted():
    result = compute_ir_calibration(_session(carpet=TAPE, tape=CARPET))
    assert result.ok, result.errors


def test_too_little_separation_is_rejected():
    result = compute_ir_calibration(_session(tape=(1260.0, 1210.0, 1310.0)))
    assert not result.ok
    assert any("span" in error for error in result.errors)
    with pytest.raises(ValueError):
        render_config(result)


def test_noisy_channel_is_rejected_even_above_min_span():
    result = compute_ir_calibration(_session(tape=(1500.0, 1450.0, 1550.0), noise=60.0))
    assert any("noise" in error for error in result.errors)


def test_missing_phase_and_rail_pinned_channel_are_rejected():
    session = _session()
    del session["centre"]
    assert any(e.startswith("centre:") for e in compute_ir_calibration(session).errors)
    session = _session()
    session["carpet"] = [[4095, v[1], v[2]] for v in session["carpet"]]
    assert any("rail" in e or "usable" in e for e in compute_ir_calibration(session).errors)


def test_swapped_left_right_wiring_fails_the_sign_check():
    session = _session()
    session["left"], session["right"] = session["right"], session["left"]
    result = compute_ir_calibration(session)
    assert not result.ok
    assert any("left tape moved the right channel" in e for e in result.errors)
    assert any("right tape moved the left channel" in e for e in result.errors)


def test_sign_errors_and_side_helpers():
    assert sign_errors({"carpet": None, "left": -0.9, "centre": 0.0, "right": 0.9}) == []
    assert len(sign_errors({"carpet": 0.1, "left": None, "centre": 0.5, "right": 0.1})) == 4
    assert [ir_side(v) for v in (None, -0.5, 0.0, 0.5)] == ["none", "left", "centre", "right"]
    levels = channel_levels([[1, 2, 3], [float("nan"), 2, 3], [True, 2, 3], [1, 2]])
    assert [level.count for level in levels] == [1, 3, 3]


def test_cli_compute_reads_a_session_offline(tmp_path, capsys):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"schema": tool.SCHEMA, "phases": _session()}), encoding="utf-8")
    assert tool.main(["compute", "--session", str(path)]) == 0
    out = capsys.readouterr().out
    assert "revision: " in out and "ir_calibration_enabled: true" in out

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": tool.SCHEMA,
                               "phases": _session(tape=(1260.0, 1210.0, 1310.0))}),
                   encoding="utf-8")
    assert tool.main(["compute", "--session", str(bad)]) == 1
    assert "FAIL:" in capsys.readouterr().out
