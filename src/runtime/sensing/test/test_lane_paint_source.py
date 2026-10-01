"""D-408: the lane keeper's paint source - an external mask, the OpenCV glare fallback, the
learned paint worker - on synthetic floors rendered through the NOMINAL ground."""
import numpy as np
import pytest

from control.sensing.perception.lane_keep import LaneKeeper, denoise_white_mask, floor_white_mask
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker
from test_lane_keep import GROUND, HALF, X_OFFSET, X, Y, _render


def _keeper():
    return LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)


def test_an_external_paint_mask_drives_the_keeper_like_the_white_threshold():
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    by_threshold = _keeper().update(image, GROUND, lane_half_width_m=HALF)
    mask = floor_white_mask(image, GROUND.horizon_row)
    keeper = _keeper()
    by_mask = keeper.update(image, GROUND, lane_half_width_m=HALF, paint_mask=mask)
    assert keeper.last["strategy"] == "both"
    assert by_mask.error == pytest.approx(by_threshold.error, abs=0.02)


def test_paint_above_the_horizon_is_ignored_and_a_wrong_size_is_refused():
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    mask = floor_white_mask(image, GROUND.horizon_row).copy()
    mask[: int(GROUND.horizon_row) + 3] = 1                  # a learned model painting the walls
    keeper = _keeper()
    seen = []
    build = keeper._birds_eye

    def spy(*args, **kwargs):                                # record the mask the keeper samples
        view = build(*args, **kwargs)
        sample = view.sample
        view.sample = lambda m: (seen.append(m.copy()), sample(m))[1]
        return view

    keeper._birds_eye = spy
    keeper.update(image, GROUND, lane_half_width_m=HALF, paint_mask=mask)
    assert keeper.last["strategy"] == "both"
    assert seen and seen[0][: int(GROUND.horizon_row) + 3].sum() == 0
    with pytest.raises(ValueError):
        _keeper().update(image, GROUND, lane_half_width_m=HALF, paint_mask=mask[:-1])


def test_denoise_removes_carpet_sparkle_but_keeps_the_tape():
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    rng = np.random.default_rng(3)
    floor = np.isfinite(X) & (np.abs(Y) < 0.06) & (X > 0.15) & (X < 0.45)   # between the lines
    sparkle = floor & (rng.random(X.shape) < 0.06)
    image[sparkle] = 230                                     # single-pixel glare
    raw = floor_white_mask(image, GROUND.horizon_row)
    clean = denoise_white_mask(image, GROUND.horizon_row)
    assert raw[sparkle].mean() > 0.5                         # the threshold reads glare as paint
    assert clean[sparkle].mean() < 0.1                       # the fallback drops it
    tape = np.isfinite(X) & (np.abs(np.abs(Y) - HALF) < 0.008) & (X > 0.15) & (X < 0.4)
    assert clean[tape].mean() > 0.7                          # and keeps the lines
    keeper = _keeper()
    keeper.update(image, GROUND, lane_half_width_m=HALF, paint_mask=clean)
    assert keeper.last["strategy"] == "both"


class _Model:
    def __init__(self, mask=None, fail=False):
        self.mask, self.fail = mask, fail

    def infer_with_mask(self, frame):
        if self.fail:
            raise RuntimeError("onnx failed")
        result = type("R", (), {"model_revision": "m1", "latency_ms": 12.0})()
        return result, (self.mask if self.mask is not None else np.ones(frame.shape[:2], np.uint8))


class _Slot:
    def __init__(self, model):
        self.model, self.last_error = model, "pointer missing"

    def poll(self):
        return self.model


def test_learned_worker_serves_a_fresh_mask_and_refuses_stale_or_mismatched_ones():
    now = [100.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=0.6, clock=lambda: now[0], start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    assert worker.latest((240, 320))[0] is None
    worker.submit(frame)
    worker.step()
    mask, summary = worker.latest((240, 320))
    assert mask is not None and summary["model_revision"] == "m1"
    assert worker.latest((120, 160))[0] is None             # another frame size
    now[0] += 0.7
    assert worker.latest((240, 320))[0] is None             # too old: the caller falls back


def test_learned_mask_age_counts_from_the_frame_not_from_the_inference():
    now = [100.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=0.6, clock=lambda: now[0], start=False)
    worker.submit(np.zeros((240, 320, 3), np.uint8))
    now[0] += 0.5                                            # inference took 0.5 s
    worker.step()
    now[0] += 0.2                                            # 0.7 s after the frame
    assert worker.latest((240, 320))[0] is None


@pytest.mark.parametrize("slot", [None, _Slot(None), _Slot(_Model(fail=True))])
def test_learned_worker_without_a_usable_model_yields_no_mask(slot):
    warnings = []
    worker = LearnedPaintWorker(slot, warn=warnings.append, start=False)
    worker.submit(np.zeros((240, 320, 3), np.uint8))
    worker.step()
    assert worker.latest((240, 320))[0] is None
    assert worker.last_error


def test_node_defaults_to_the_threshold_and_falls_back_to_denoise():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    assert "self.declare_parameter('paint_source', 'threshold', _READ_ONLY)" in src
    assert "'denoise_fallback'" in src and "paint_source_used=paint_used" in src
