"""core_events suite bootstrap — colcon-less pytest needs the package roots.

Same pattern as core/test/conftest.py: the source dirs go on sys.path so
`import core_events...` resolves without a ROS overlay.
"""

from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[4]
for _dir in (REPO / "middleware" / "core" / "events", REPO / "contracts" / "foundation"):
    _path = str(_dir)
    if _path not in sys.path:
        sys.path.insert(0, _path)
