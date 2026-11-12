"""Raw ROS camera decoding used by the simulation evidence recorder."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_image_bgr_accepts_rgb_rows_with_padding():
    path = Path(__file__).resolve().parents[1] / 'tools/sim/fleet_trip_recorder.py'
    spec = importlib.util.spec_from_file_location('fleet_trip_recorder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    msg = SimpleNamespace(encoding='rgb8', width=1, height=2, step=4,
                          data=bytes([10, 20, 30, 0, 40, 50, 60, 0]))
    assert module.image_bgr(msg).tolist() == [[[30, 20, 10]], [[60, 50, 40]]]
    msg.step = 2
    with pytest.raises(ValueError):
        module.image_bgr(msg)
