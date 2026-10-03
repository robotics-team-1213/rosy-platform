"""D-339 Decision 1: the folder names the role; the ROS package name stays (D-231).

Every package whose folder basename differs from its `package.xml` <name> must be
listed here, and every entry here must still match the tree. A new folder whose
package name differs goes into this table in the same commit.
"""

import os
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "harness"))
from colcon_roots import colcon_roots  # noqa: E402

SKIP_DIRS = {"build", "install", "log", ".worktrees", ".git", "node_modules", "__pycache__"}

# Repo-relative folder (D-427: every colcon root, so moves rewrite these as plain paths)
# -> ROS package name. Mirrored in src/AGENTS.md.
FOLDER_TO_PACKAGE = {
    "contracts/foundation": "core_common",
    "middleware/ui/face": "emotion",
    "middleware/ui/robot": "dashboard",
    "shared/web": "web_common",
    "middleware/apps/device/omx/adapter": "omx_adapter",
    "middleware/apps/device/omx/profile": "omx",
    "middleware/drivers/pinky_adc": "sensor_adc",
    "middleware/drivers/pinky_lamp": "lamp_control",
    "middleware/apps/device/pinky/profile": "pinky_pro",
    "middleware/core/api_web": "core_api_web",
    "middleware/core/events": "core_events",
    "middleware/core/gateway": "core",
    "src/runtime/sensing": "control",
    "middleware/core/services": "core_features",
    "operations/vision": "rosy_vision",  # D-377 rosy_<word>; D-427 target folder is the word itself
    "operations/processes/cell": "rosy_cell",
    "learning/envs/isaac": "isaac_sim",
    "middleware/drivers/pinky_led": "led",
    "integrations/simulation/gazebo": "gz_sim",
}


def _packages():
    """repo-relative folder -> package name over every colcon root,
    skipping build trees and COLCON_IGNORE."""
    found = {}
    for dirpath, dirnames, filenames in (step for top in colcon_roots() for step in os.walk(ROOT / top)):
        if "COLCON_IGNORE" in filenames:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        if "package.xml" in filenames:
            folder = Path(dirpath)
            name = ET.parse(folder / "package.xml").getroot().findtext("name", "").strip()
            found[folder.relative_to(ROOT).as_posix()] = name
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
