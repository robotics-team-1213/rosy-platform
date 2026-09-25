"""rosylib's battery curve is CORE's curve, copied not imported (D-192).

rosy-io must not import CORE (core_features pulls core_common and pydantic),
so rosylib.battery carries its own copy of DEFAULT_CURVE_2S. This pins the
copy and the interpolation equal to core_features.power.battery.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]  # repository root
for path in (ROOT / "src/devices/bringup", ROOT / "src/runtime/core_features",
             ROOT / "src/contracts/core_common", ROOT / "src/runtime/core_events"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core_features.power.battery import DEFAULT_CURVE_2S, BatteryCurve  # noqa: E402
from rosylib import battery as rosylib_battery  # noqa: E402


def test_the_table_is_cores_table():
    assert rosylib_battery.CURVE_2S == DEFAULT_CURVE_2S


@pytest.mark.parametrize("millivolts", range(6000, 8801, 7))
def test_percent_matches_battery_curve_default(millivolts):
    voltage = millivolts / 1000.0
    assert rosylib_battery.voltage_to_percent(voltage) == pytest.approx(
        BatteryCurve.default().percent(voltage), abs=1e-9)


def test_rosylib_does_not_import_core():
    for source in (ROOT / "src/devices/bringup/rosylib").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "import core" not in text and "from core" not in text, source
