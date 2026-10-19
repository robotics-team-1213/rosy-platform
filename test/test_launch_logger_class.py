"""A test that imports ROS 2 ``launch`` gives the logger class back right away.

``launch.logging`` calls ``logging.setLoggerClass(LaunchLogger)`` on first import, and
``LaunchLogger`` sets ``propagate = False``. Every logger created later in the same pytest
process then skips the root handlers, so ``caplog`` in an unrelated suite sees nothing
(2026-10-17: ``test_situation_service`` failed in CI after the gazebo tests were collected).
Static check over tracked files; it does not need ROS.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS_LAUNCH = re.compile(r"""importorskip\(\s*["']launch(?:\.[\w.]+)?["']""")
RESTORE = "logging.setLoggerClass(logging.Logger)"


def _tracked_tests() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*test_*.py"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return out.split()


def test_every_launch_import_restores_the_logger_class():
    importers = [p for p in _tracked_tests()
                 if IMPORTS_LAUNCH.search((ROOT / p).read_text(encoding="utf-8"))]
    assert len(importers) >= 4, importers  # the scan itself still finds the known importers
    missing = [p for p in importers if RESTORE not in (ROOT / p).read_text(encoding="utf-8")]
    assert missing == [], f"import ROS 2 launch, then call {RESTORE}: {missing}"
