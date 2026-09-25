"""core_features suite bootstrap — colcon-less pytest needs the package roots.

test_docking.py imports `control.sensor_provider`; the control path exists
only for that adapter, mirroring core/test/conftest.py (D-126: production
core_features code never imports control — tests are not coupling, D-168 P3).
"""

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2]
for _path in (
    SRC / "services",
    SRC.parent / "contracts" / "foundation",
    SRC / "sensing",
):
    _entry = str(_path)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
