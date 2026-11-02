"""Run without colcon install: perception_runtime and core_common from the source tree."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "integrations" / "perception", ROOT / "contracts" / "foundation"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
