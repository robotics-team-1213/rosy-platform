"""Make the ROS-free ``bringup`` package importable without a colcon install.

The package test AGENTS documents
``pytest src/hardware/bringup/test/test_command_deadman.py`` from the repo
root, but ``bringup`` only lands on ``sys.path`` when a workspace install is
sourced. On a plain host that made the whole directory a collection error —
deadman contract included. Point the interpreter at the source tree instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[1])

if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)
