import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "tools" / "perception" / "dataset", ROOT / "src" / "runtime" / "sensing",
          ROOT / "src" / "contracts" / "foundation"):  # core_common, needed by control (D-424)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
