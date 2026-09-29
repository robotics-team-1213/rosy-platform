"""D-339 Decision 1: the folder names the role; the ROS package name stays (D-231).

Every package whose folder basename differs from its `package.xml` <name> must be
listed here, and every entry here must still match the tree. A new folder whose
package name differs goes into this table in the same commit.
"""

import os
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SKIP_DIRS = {"build", "install", "log", ".worktrees", ".git", "node_modules", "__pycache__"}

# Relative folder under src/ -> ROS package name. Mirrored in src/AGENTS.md.
FOLDER_TO_PACKAGE = {
    "contracts/foundation": "core_common",
    "hmi/face": "emotion",
    "products/omx/adapter": "omx_adapter",
    "products/omx/profile": "omx",
    "products/pinky_pro/adc": "sensor_adc",
    "products/pinky_pro/lamp": "lamp_control",
    "products/pinky_pro/profile": "pinky_pro",
    "runtime/api_web": "core_api_web",
    "runtime/events": "core_events",
    "runtime/gateway": "core",
    "runtime/sensing": "control",
    "runtime/services": "core_features",
}


def _packages():
    """folder (relative to src/) -> package name, skipping build trees and COLCON_IGNORE."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(SRC):
        if "COLCON_IGNORE" in filenames:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        if "package.xml" in filenames:
            folder = Path(dirpath)
            name = ET.parse(folder / "package.xml").getroot().findtext("name", "").strip()
            found[folder.relative_to(SRC).as_posix()] = name
    return found


def test_the_tree_has_packages():
    assert len(_packages()) > len(FOLDER_TO_PACKAGE)


def test_every_folder_package_mismatch_is_listed():
    mismatched = {
        folder: name for folder, name in _packages().items()
        if Path(folder).name != name
    }
    assert mismatched == FOLDER_TO_PACKAGE


def test_the_table_has_no_stale_entries():
    packages = _packages()
    stale = [
        folder for folder, name in FOLDER_TO_PACKAGE.items()
        if packages.get(folder) != name or Path(folder).name == name
    ]
    assert stale == []
