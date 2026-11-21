"""D-1057: the depth burst (N consecutive Z16 frames) and the per-pixel median that lowers the frame noise."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_depth_slots as slots  # noqa: E402

DEVICE = __file__  # any existing path stands in for the V4L2 node


def test_the_median_of_five_frames_has_a_lower_standard_deviation_than_one_frame():
    rng = np.random.default_rng(3)
    true = np.full((480, 640), 600.0)
    frames = np.stack([(true + rng.normal(0, 2.0, true.shape)).round() for _ in range(5)]).astype(np.uint16)
    median, valid = slots.median_depth(frames)
    assert valid == 1.0
    assert np.std(median.astype(float) - true) < 0.75 * np.std(frames[0].astype(float) - true)  # about 1/sqrt(5) * 1.25 = 0.56


def test_a_pixel_needs_more_than_half_of_the_frames_valid():
    frames = np.full((5, 4, 4), 500, np.uint16)
    frames[:3, 0, 0] = 0   # 2 of 5 valid: out
    frames[:2, 1, 1] = 0   # 3 of 5 valid: in
    frames[:, 2, 2] = 0    # none valid
    frames[0, 3, 3], frames[1, 3, 3] = 700, 600  # the median ignores the invalid zeros
    median, valid = slots.median_depth(frames)
    assert median[0, 0] == 0 and median[1, 1] == 500 and median[2, 2] == 0 and median[3, 3] == 500
    assert valid == pytest.approx(14 / 16)


def _runner(frames=5, record=None, fail_first=False, flag=True, used=614400, seq_gap=False, stale_first=False, clock_jump=0.0):
    def run(cmd, timeout, check, stdout, stderr, text):
        if record is not None:
            record.append((list(cmd), timeout))
        if fail_first and "--set-fmt-video=width=640,height=480,pixelformat=Z16" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="format refused")
        raw = Path(next(c for c in cmd if c.startswith("--stream-to=")).split("=", 1)[1])
        import time

        base = time.monotonic() - 1.2  # the burst ran just before this call returned
        raw.write_bytes(np.full((frames, 480, 640), 640, "<u2").tobytes())
        stamps = [base + 0.07 * i for i in range(17)]
        seqs = list(range(17))
        if seq_gap:
            seqs[14] = 20
        if stale_first:
            stamps[12] = base - 5.0  # the first kept frame was exposed long before this capture
        suffix = " flags: ts-monotonic, ts-src-soe" if flag else ""
        lines = "".join(f"cap dqbuf: 0 seq: {s} bytesused: {used} ts: {t:.6f}{suffix}\n" for s, t in zip(seqs, stamps))
        if clock_jump:
            real = time.time
            time.time = lambda: real() + clock_jump  # the wall clock steps while the burst runs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=lines)

    return run


def test_the_burst_is_one_stream_of_n_frames_inside_the_limit(tmp_path):
    record = []
    frames, receipt = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(record=record))
    assert frames.shape == (5, 480, 640) and receipt["frames"] == 5 and receipt["source_seq_last"] == 16
    cmd, timeout = record[0]
    assert "--stream-count=5" in cmd and "--stream-skip=12" in cmd and f"--set-parm={slots.DEPTH_FPS}" in cmd
    assert timeout <= slots.DEPTH_BURST_S == 3.0
    assert receipt["exposure_wall_estimate_s"] > receipt["first_exposure_wall_estimate_s"]


@pytest.mark.parametrize("kwargs, reason", [
    ({"frames": 4}, "wrong number"),
    ({"flag": False}, "start-of-exposure monotonic"),
    ({"used": 600000}, "exact size"),
    ({"seq_gap": True}, "consecutive"),
    ({"stale_first": True}, "not from this capture"),
])
def test_every_kept_frame_is_checked_like_the_single_frame_capture(tmp_path, kwargs, reason):
    frames, why = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(**kwargs))
    assert frames is None and reason in why


def test_a_wall_clock_step_during_the_burst_is_refused(tmp_path, monkeypatch):
    import time

    real = time.time
    frames, why = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(clock_jump=2.0))
    time.time = real
    assert frames is None and "wall clock moved" in why


def test_one_deadline_covers_the_format_retry_too(tmp_path):
    record = []
    frames, _ = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(fail_first=True, record=record))
    assert frames is not None and len(record) == 2 and "--set-fmt-video=width=640,height=480,pixelformat=Z16 " in record[1][0]
    assert record[1][1] <= record[0][1] <= 3.0  # the retry gets what is left of the one deadline, never a fresh 3 s
    assert slots.capture_depth_frames(str(tmp_path / "missing"), 5, tmp_path / "d.raw", run=_runner())[1] == "depth device missing"

    def slow_fail(cmd, timeout, **kw):
        import time as _t

        _t.sleep(0.35)
        raise subprocess.CalledProcessError(1, cmd, stderr="refused")

    frames, why = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", timeout_s=0.5, run=slow_fail)
    assert frames is None and "TimeoutExpired" in why  # no second attempt past the shared deadline

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("v4l2-ctl", 3.0)

    frames, why = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=timeout)
    assert frames is None and "TimeoutExpired" in why
