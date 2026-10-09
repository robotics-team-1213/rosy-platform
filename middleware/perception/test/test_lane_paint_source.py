"""D-408: the lane keeper's paint source - an external mask, the OpenCV glare fallback, the
learned paint worker - on synthetic floors rendered through the NOMINAL ground."""
import numpy as np
import pytest

from control.sensing.perception.lane_keep import LaneKeeper, clean_learned_mask, denoise_white_mask, floor_white_mask
from control.sensing.perception.lane_keep_lines import DENOISE_MIN_AREA_PX
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
        self.mask, self.fail, self.calls = mask, fail, 0

    model_revision = "m1"

    def infer_mask(self, frame):
        if self.fail:
            raise RuntimeError("onnx failed")
        self.calls += 1
        return (self.mask if self.mask is not None else np.ones(frame.shape[:2], np.uint8)), 12.0


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


def test_learned_mask_drops_speckle_keeps_tape_and_cuts_the_horizon():
    mask = np.zeros((240, 320), np.uint8)
    mask[150:200, 100:104] = 1                               # tape: 200 px
    mask[160, 200] = 1                                       # speckle
    mask[170:172, 220:222] = 1                               # 4 px blob
    side = int(np.sqrt(DENOISE_MIN_AREA_PX))
    mask[210:210 + side, 250:250 + side] = 1                 # side^2 = 36 < 40 px
    mask[10:60, 10:14] = 1                                   # above the horizon (a wall)
    clean = clean_learned_mask(mask, horizon_row=100.0)
    assert clean[150:200, 100:104].all()
    assert clean[160, 200] == 0 and clean[170:172, 220:222].sum() == 0
    assert clean[:100].sum() == 0
    assert side * side < DENOISE_MIN_AREA_PX and clean[210:210 + side, 250:250 + side].sum() == 0


def test_every_n_submits_each_nth_frame_and_reuses_the_mask_in_between():
    now = [100.0]
    model = _Model()
    worker = LearnedPaintWorker(_Slot(model), stale_s=0.6, clock=lambda: now[0], start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    served = []
    for _ in range(6):
        served.append(worker.mask_for(frame, every_n=2) is not None)
        worker.step()                                        # inference finishes before the next frame
        now[0] += 0.125
    assert model.calls == 3                                  # frames 0, 2, 4
    assert served == [False, True, True, True, True, True]   # frame 0 has none yet; then reused


def test_every_n_refuses_a_mask_older_than_n_frames_and_a_stale_one():
    now = [100.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=0.6, clock=lambda: now[0], start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, every_n=2)                        # frame 0 submitted
    worker.step()
    assert worker.mask_for(frame, every_n=2) is not None     # frame 1: 1 frame old
    assert worker.mask_for(frame, every_n=2) is not None     # frame 2: 2 frames old, new submit pending
    worker._pending = None                                   # the inference never completes
    assert worker.mask_for(frame, every_n=2) is None         # frame 3: 3 > n frames old
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=0.6, clock=lambda: now[0], start=False)
    worker.mask_for(frame, every_n=4)
    worker.step()
    now[0] += 0.7
    assert worker.mask_for(frame, every_n=4) is None         # within n frames but past stale_s


def test_reported_revision_belongs_only_to_the_served_fresh_mask():
    now = [100.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=0.6, clock=lambda: now[0], start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    assert worker.mask_for(frame, every_n=2) is None
    assert worker.used_model_revision is None
    worker.step()
    assert worker.mask_for(frame, every_n=2) is not None
    assert worker.used_model_revision == 'm1'
    now[0] += 0.7
    assert worker.mask_for(frame, every_n=2) is None
    assert worker.used_model_revision is None
    worker.reset()
    assert worker.used_model_revision is None


def test_paint_path_does_not_compute_lane_evidence(monkeypatch):
    from control.sensing.perception.learned import runner
    from test_learned_runner import _factory, _model_dir
    import tempfile
    from pathlib import Path
    calls = []
    monkeypatch.setattr(runner, "lane_evidence", lambda *a, **k: calls.append(1))
    with tempfile.TemporaryDirectory() as tmp:
        model = runner.LaneSegModel.open(_model_dir(Path(tmp)), session_factory=_factory())
        mask, latency_ms = model.infer_mask(np.zeros((240, 320, 3), np.uint8))
    assert mask.shape == (240, 320) and mask.any() and latency_ms >= 0 and not calls


def test_open_passes_allow_spinning_to_the_default_session(tmp_path, monkeypatch):
    from control.sensing.perception.learned import runner
    from test_learned_runner import _factory, _model_dir
    seen = []

    class Session:
        def __init__(self, path, threads, allow_spinning=True):
            seen.append((threads, allow_spinning))
            self._fake = _factory()(path, threads)

        def run(self, x):
            return self._fake.run(x)

    monkeypatch.setattr(runner, "_OrtSession", Session)
    runner.LaneSegModel.open(_model_dir(tmp_path, "a"), threads=1, allow_spinning=False)
    runner.LaneSegModel.open(_model_dir(tmp_path, "b"))
    assert seen == [(1, False), (2, True)]                   # the shadow node keeps its defaults


def test_ort_session_options_disable_spinning():
    ort = pytest.importorskip("onnxruntime")
    from control.sensing.perception.learned import runner
    entries = {}
    real = ort.SessionOptions

    class Options(real):
        def add_session_config_entry(self, key, value):
            entries[key] = value
            super().add_session_config_entry(key, value)

    ort.SessionOptions = Options
    try:
        with pytest.raises(Exception):                       # no such file: only the options matter
            runner._OrtSession("missing.onnx", 1, allow_spinning=False)
    finally:
        ort.SessionOptions = real
    assert entries == {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"}


def test_node_wires_the_paint_cadence_and_session_options():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    assert "declare_parameter('learned_paint_every_n', 2, _READ_ONLY)" in src
    assert "declare_parameter('learned_paint_threads', 1, _READ_ONLY)" in src
    assert "threads=threads, allow_spinning=False" in src and "clean_learned_mask(m, ground.horizon_row)" in src


def _stamped(worker, n, every_n, t, step=True, dt=0.125, clean=None):
    out = []
    for _ in range(n):
        out.append(worker.mask_for(np.zeros((240, 320, 3), np.uint8), every_n, t[0], clean))
        if step:
            worker.step()
        t[0] += dt
    return out


def test_reuse_is_bound_by_frame_stamps_not_call_counts():
    t = [10.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=5.0, clock=lambda: 0.0, start=False)
    _stamped(worker, 3, 2, t)                                # 8 Hz frames teach the period
    worker._pending = None                                   # no new mask arrives
    t[0] += 0.5                                              # then a long camera pause, 1 call later
    assert worker.mask_for(np.zeros((240, 320, 3), np.uint8), 2, t[0]) is None   # 0.6 s > 1.5*2*0.125


def test_reset_clears_cached_mask_pending_frame_and_counter():
    t = [10.0]
    model = _Model()
    worker = LearnedPaintWorker(_Slot(model), stale_s=5.0, clock=lambda: 0.0, start=False)
    _stamped(worker, 2, 2, t)
    assert worker.mask_for(np.zeros((240, 320, 3), np.uint8), 2, t[0]) is not None
    worker.reset()
    assert worker.latest((240, 320))[0] is None and worker._frames == 0 and worker._pending is None
    worker.step()
    assert model.calls == 1                                  # nothing pending survived the reset
    # an inference that was running during the reset must not repopulate the cache
    worker.submit(np.zeros((240, 320, 3), np.uint8), tag=0, stamp=t[0])
    pending = worker._pending
    worker._pending = None
    worker.reset()
    worker._pending = pending                                # the stale generation's frame
    worker.step()
    assert worker.latest((240, 320))[0] is None


def test_a_reused_mask_is_cleaned_once_per_new_mask():
    t = [10.0]
    worker = LearnedPaintWorker(_Slot(_Model()), stale_s=5.0, clock=lambda: 0.0, start=False)
    cleaned = []

    def clean(m):
        cleaned.append(1)
        return m

    got = _stamped(worker, 4, 2, t, clean=clean)             # submits at frames 0 and 2 -> 2 masks
    assert [g is not None for g in got] == [False, True, True, True]
    assert len(cleaned) == 2


def test_mask_cache_and_revision_share_one_atomic_result_snapshot():
    worker = LearnedPaintWorker(None, clock=lambda: 10.0, start=False)
    frame = np.zeros((8, 8, 3), np.uint8)
    old = (10.0, np.ones((8, 8), np.uint8), dict(tag=0, stamp=10.0, model_revision='old'))
    new = (10.0, np.zeros((8, 8), np.uint8), dict(tag=1, stamp=10.0, model_revision='new'))
    worker._result = old
    worker._clean_cache = (old, old[1])
    # Complete inference exactly between the old implementation's two reads.
    original_latest = worker.latest
    def interleaved_latest(shape):
        worker._result = new
        return original_latest(shape)
    worker.latest = interleaved_latest
    mask = worker.mask_for(frame, every_n=2, stamp=10.0, clean=lambda m: m.copy())
    assert mask.all()  # one snapshot: either old/old or new/new, never old mask/new revision
    assert worker.used_model_revision == 'old'


def test_cadence_one_while_turning_infers_every_frame():
    t = [10.0]
    model = _Model()
    worker = LearnedPaintWorker(_Slot(model), stale_s=5.0, clock=lambda: 0.0, start=False)
    _stamped(worker, 4, 1, t)
    assert model.calls == 4


def test_node_gates_reuse_on_turn_rate_and_resets_the_worker():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    assert "declare_parameter('learned_paint_reuse_max_wz', 0.15)" in src
    assert "abs(wz) > float(self.get_parameter('learned_paint_reuse_max_wz').value)" in src
    assert src.count("self._paint_worker.reset()") >= 4
    assert "self._odom_twist = (float(msg.twist.twist.linear.x), float(msg.twist.twist.angular.z))" in src
    assert "pose_if_fresh(self._odom_twist and self._odom_twist[1], self._odom_stamp, stamp)" in src


def test_ort_session_options_with_a_fake_onnxruntime(monkeypatch):
    import sys
    from control.sensing.perception.learned import runner
    entries = {}

    class Options:
        intra_op_num_threads = 0
        inter_op_num_threads = 0

        def add_session_config_entry(self, key, value):
            entries[key] = value

    class Session:
        def __init__(self, path, sess_options=None, providers=None):
            self.opts = sess_options

        def get_inputs(self):
            return [type("I", (), {"name": "x"})()]

    fake = type(sys)("onnxruntime")
    fake.SessionOptions, fake.InferenceSession = Options, Session
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    monkeypatch.setattr(runner, "add_learned_site", lambda: None)
    spin_off = runner._OrtSession("m.onnx", 1, allow_spinning=False)
    assert entries == {"session.intra_op.allow_spinning": "0", "session.inter_op.allow_spinning": "0"}
    assert spin_off._s.opts.intra_op_num_threads == 1 and spin_off._s.opts.inter_op_num_threads == 1
    entries.clear()
    default = runner._OrtSession("m.onnx", 2)
    assert entries == {} and default._s.opts.intra_op_num_threads == 2
