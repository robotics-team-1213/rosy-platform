"""Make the ``emotion`` package importable without a colcon install.

Its tests import ``emotion.info_screen`` directly; without a sourced
workspace install the interpreter cannot see the package next door and the
whole directory fails collection on a plain host. Point at the source tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[1])

if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)
