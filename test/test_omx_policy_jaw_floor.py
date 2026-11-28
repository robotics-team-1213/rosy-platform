"""Policy chunks never command the jaw below the reviewed empty-jaw stop (2026-11-28 arm_s false HOLDING)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_paced as paced  # noqa: E402
import cell_policy_shape as shape  # noqa: E402
from test_omx_paced_handoff import HoldCell, Policy, _run  # noqa: E402

LOW = [-30.0, -60.0, 0.0, 20.0, -35.0, 40.0]
HIGH = [30.0, 20.0, 60.0, 60.0, 50.0, 65.0]
START = [0.0, -20.0, 30.0, 40.0, 0.0, 55.0]


def _chunk(jaw):
    return [[0.0, -20.0, 30.0, 40.0, 0.0, g] for g in jaw]


def test_jaw_below_floor_is_raised_and_other_columns_untouched():
    out = np.asarray(shape.shape_chunk(_chunk([46.6, 47.5, 50.0]), START, LOW, HIGH, 100.0, jaw_floor=49.0))
    assert out[:, 5].min() >= 49.0 and out[-1, 5] == pytest.approx(50.0)
    assert np.allclose(out[:, :5], np.asarray(START[:5]))


def test_jaw_above_floor_is_unchanged():
    chunk = _chunk([52.0, 55.0])
    assert shape.shape_chunk(chunk, START, LOW, HIGH, 100.0, jaw_floor=49.0) == shape.shape_chunk(chunk, START, LOW, HIGH, 100.0)


def test_no_floor_keeps_old_output():
    out = shape.shape_chunk(_chunk([46.6, 47.5]), START, LOW, HIGH, 100.0)
    assert out[-1][5] == pytest.approx(47.5) and min(r[5] for r in out) < 49.0


def test_paced_path_passes_the_empty_stop_as_floor(tmp_path, monkeypatch):
    import cell_policy_shape as cps
    seen = {}
    real = cps.shape_chunk
    monkeypatch.setattr(cps, "shape_chunk", lambda *a, **kw: seen.update(kw) or real(*a, **kw))
    from test_omx_paced_handoff import _handoff, GOOD
    handoff, _ = _handoff(tmp_path, monkeypatch, GOOD)
    _run(HoldCell(), handoff, tmp_path, [])
    assert seen.get("jaw_floor") == 46.6  # the harness passes closed=46.6
