"""D-196: robot-specific names live in the robot's device family and robot package.

Every other product file under src/ that still says "pinky" is listed in
robot_literal_backlog.txt and checked by set equality (D-168 P5): a new hit
fails, and so does a line whose file no longer matches. Shrinking the list is
the de-Pinky work (plan P5).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BACKLOG = Path(__file__).with_name("robot_literal_backlog.txt")
PATTERN = re.compile(r"pinky", re.IGNORECASE)
SUFFIXES = {".py", ".yaml", ".yml", ".xml", ".xacro", ".urdf", ".sdf", ".world", ".cpp", ".hpp", ".json"}
SKIP_PARTS = {"test", "tests", "build", "install", "log", "__pycache__"}
HOME_PREFIXES = ("devices/pinky_pro/", "products/pinky_pro")


def hits() -> set:
    found = set()
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        rel = path.relative_to(SRC)
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel.parts):
            continue
        key = rel.as_posix()
        if key.startswith(HOME_PREFIXES):
            continue
        if PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
            found.add(key)
    return found


def backlog() -> set:
    lines = BACKLOG.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_robot_literals_stay_in_their_family():
    found, known = hits(), backlog()
    assert found == known, f"new: {sorted(found - known)}, stale (remove): {sorted(known - found)}"
