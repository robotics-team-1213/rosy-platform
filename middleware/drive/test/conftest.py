"""Pinky drive-stack pure-logic tests (moved out of middleware/perception/test, split round 3).

`control.*` resolves through the root conftest; core_common is added for the calibration-step tests."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "contracts" / "foundation"))
