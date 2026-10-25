"""Every TRIP_* code Fleet raises has operator text in the console (D-517 10).

A code without a label shows the raw code ("경로 계획 거절 (TRIP_...)") to the operator.
"""

import re
from pathlib import Path

FLEET = Path(__file__).resolve().parents[1] / "fleet"
DISPLAY = Path(__file__).resolve().parents[3] / "applications/fleet/web/shared/trip-display.js"


def test_every_trip_code_has_console_text():
    raised = set()
    for path in FLEET.rglob("*.py"):
        raised |= set(re.findall(r"""["'](TRIP_[A-Z_]+)["']""", path.read_text(encoding="utf-8")))
    labelled = set(re.findall(r"(?:^|,)\s*(TRIP_[A-Z_]+):", DISPLAY.read_text(encoding="utf-8"), re.M))
    assert raised - labelled == set()
