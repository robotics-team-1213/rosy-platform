"""core_events suite bootstrap — colcon-less pytest needs the package roots.

Same pattern as core/test/conftest.py: the source dirs go on sys.path so
`import core_events...` resolves without a ROS overlay.
"""

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2]
for _name in ("core_events", "core_common"):
    _path = str(SRC / _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)
