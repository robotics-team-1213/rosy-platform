"""web_common suite bootstrap — colcon-less pytest needs the package roots.

test_ui_token_contracts builds the real FastAPI app, so core_api_web's
routers (and their core_features/core_common imports) must resolve too.
tokens.css / core_ui_logic.js are read by path relative to this file, so the
move from core/test kept the same directory depth.
"""

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[3]
_ROOTS = {
    "core_api_web": SRC / "runtime" / "api_web",
    "core_features": SRC / "runtime" / "features",
    "core_common": SRC / "contracts" / "foundation",
}
for _name in _ROOTS:
    _path = str(_ROOTS[_name])
    if _path not in sys.path:
        sys.path.insert(0, _path)
