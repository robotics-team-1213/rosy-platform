"""D-196/D-310: robot-specific names live in the product source family.

Every other product file under src/ that still says "pinky" is listed in
robot_literal_backlog.txt and checked by set equality (D-168 P5): a new hit
fails, and so does a line whose file no longer matches. Shrinking the list is
the de-Pinky work (plan P5).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BACKLOG = Path(__file__).with_name("robot_literal_backlog.txt")
PATTERN = re.compile(r"pinky", re.IGNORECASE)
SUFFIXES = {".py", ".yaml", ".yml", ".xml", ".xacro", ".urdf", ".sdf", ".world", ".cpp", ".hpp", ".json"}
SKIP_PARTS = {"test", "tests", "build", "install", "log", "__pycache__"}
#: D-427: repo-relative. The Pinky family before (src/products/pinky_pro) and after wave 4c.
HOME_PREFIXES = ("src/products/pinky_pro/", "middleware/apps/device/pinky/bringup/",
                 "middleware/apps/device/pinky/profile/", "middleware/drivers/pinky_adc/",
                 "middleware/drivers/pinky_lamp/", "middleware/drivers/pinky_led/")
#: D-427: product code leaves src/ for these part roots (learning is out of scope).
SCAN_ROOTS = ("src", "operations", "middleware", "contracts", "shared", "integrations")


@pytest.mark.parametrize("text,expected", [("class PinkyTwistPort: pass", False),
                                           ('class PinkyTwistPort: pass\nDEFAULT_MODEL="pinky_pro"', True),
                                           ('GUARD_REVISION="pinky-anything"', True)])
def test_writer_binding_type_name_never_exempts_robot_configuration_literals(text, expected):
    assert _has_robot_literal("middleware/core/gateway/core/bridge/cmd_vel.py", text) is expected


def _has_robot_literal(path, text):
    # Accepted D-442 U2 places this exact binding type beside the existing
    # writer. Exempt its type name only, never the file or other robot values.
    if path == "middleware/core/gateway/core/bridge/cmd_vel.py":
        text = re.sub(r"\bPinkyTwistPort\b", "DeviceTwistPort", text)
    return PATTERN.search(text) is not None


def hits() -> set:
    found = set()
    for path in (path for root in SCAN_ROOTS for path in (ROOT / root).rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts[1:]):
            continue
        key = rel.as_posix()
        if key.startswith(HOME_PREFIXES):
            continue
        if _has_robot_literal(key, path.read_text(encoding="utf-8", errors="ignore")):
            found.add(key)
    return found


def backlog() -> set:
    lines = BACKLOG.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_robot_literals_stay_in_their_family():
    found, known = hits(), backlog()
    assert found == known, f"new: {sorted(found - known)}, stale (remove): {sorted(known - found)}"
