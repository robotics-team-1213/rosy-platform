import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for p in (ROOT / "learning" / "training" / "perception" / "dataset", ROOT / "middleware" / "perception",
          ROOT / "contracts" / "foundation"):  # core_common, needed by control (D-424)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
