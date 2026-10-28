"""Network load: the robot updater's tarball download is paced (deploy/robot/pinky_pro/native/rosy_transfer.py)."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"))
import rosy_transfer  # noqa: E402


def test_paced_download_sleeps_down_to_the_limit_and_zero_is_unlimited():
    slept = []
    body = io.BytesIO(b"x" * 250_000)            # 2 Mbit at 2000 kbit/s: 1 s in total
    chunks = list(rosy_transfer.paced(body, 2000, clock=lambda: 0.0, sleep=slept.append))
    assert chunks[-1][0] == 250_000 and b"".join(c for _, c in chunks) == b"x" * 250_000
    assert abs(slept[-1] - 1.0) < 1e-9
    slept.clear()
    assert [n for n, _ in rosy_transfer.paced(io.BytesIO(b"y" * 10), 0, sleep=slept.append)] == [10]
    assert slept == []


def test_the_limit_comes_from_the_environment_with_a_2_mbit_default():
    assert rosy_transfer.limit_kbps({}) == 2000
    assert rosy_transfer.limit_kbps({"ROSY_UPDATE_LIMIT_KBPS": "0"}) == 0
    assert rosy_transfer.limit_kbps({"ROSY_UPDATE_LIMIT_KBPS": "-5"}) == 2000
