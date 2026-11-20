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


def _runner(frames=5, bad_stamps=False, fail_first=False, record=None):
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
        if bad_stamps:
            stamps[-1] = stamps[-2]
        lines = "".join(f"cap dqbuf: 0 seq: {i} bytesused: 614400 ts: {t:.6f}\n" for i, t in enumerate(stamps))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=lines)

    return run


def test_the_burst_is_one_stream_of_n_frames_inside_the_limit(tmp_path):
    record = []
    frames, receipt = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(record=record))
    assert frames.shape == (5, 480, 640) and receipt["frames"] == 5 and receipt["source_seq_last"] == 16
    cmd, timeout = record[0]
    assert "--stream-count=5" in cmd and "--stream-skip=12" in cmd and f"--set-parm={slots.DEPTH_FPS}" in cmd
    assert timeout == slots.DEPTH_BURST_S == 3.0
    assert receipt["exposure_wall_estimate_s"] > receipt["first_exposure_wall_estimate_s"]


def test_the_burst_retries_the_format_spelling_once_and_refuses_bad_captures(tmp_path):
    record = []
    frames, _ = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(fail_first=True, record=record))
    assert frames is not None and len(record) == 2 and "--set-fmt-video=width=640,height=480,pixelformat=Z16 " in record[1][0]
    assert slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(frames=4))[0] is None        # wrong size
    assert slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=_runner(bad_stamps=True))[0] is None  # stamps not consecutive
    assert slots.capture_depth_frames(str(tmp_path / "missing"), 5, tmp_path / "d.raw", run=_runner())[1] == "depth device missing"

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("v4l2-ctl", 3.0)

    frames, why = slots.capture_depth_frames(DEVICE, 5, tmp_path / "d.raw", run=timeout)
    assert frames is None and "TimeoutExpired" in why
