"""D-229: perception, decision, and geometry do not import each other's jobs."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERCEPTION = ROOT / "src/runtime/sensing/control/sensing/perception"
DECISION = ROOT / "src/runtime/services/core_features/decision"
LINE = ROOT / "src/runtime/services/core_features/line_follow"
SENSING = ROOT / "src/runtime/sensing/control/sensing"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _hits(directory: Path, banned: tuple[str, ...]) -> list[str]:
    bad = []
    for path in directory.glob("*.py"):
        for name in _imports(path):
            if any(name == item or name.startswith(item + ".") for item in banned):
                bad.append(f"{path.name}: {name}")
    return bad


def test_perception_does_not_import_decision_or_ros():
    assert _hits(PERCEPTION, ("rclpy", "core_features", "line_follow")) == []


def test_decision_does_not_import_perception_or_vision():
    assert _hits(DECISION, ("control", "rclpy", "cv2", "line_follow", "sensing")) == []


def test_line_follow_reads_decisions_not_pixels():
    assert _hits(LINE, ("control", "cv2", "rclpy", "sensing")) == []
    wired = "\n".join(_imports(LINE / "manager.py"))
    assert "core_features.decision.lane" in wired


def test_geometry_package_does_not_import_perception():
    bad = []
    for path in SENSING.glob("*.py"):
        for name in _imports(path):
            if "perception" in name.split("."):
                bad.append(f"{path.name}: {name}")
    assert bad == []
