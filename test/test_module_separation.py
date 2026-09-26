"""D-126: full module separation guards on the new src layout.

Scope notes (honest holes, not oversights):
- "Production code" = *.py outside any test/ directory. Operator tooling under
  control/tools/ is excluded from guard 2: measuring the final topic is its job.
- Guard 3 covers Python imports plus C++ #includes of workspace packages only;
  third-party deps (rclpy, std_msgs, ...) are out of scope.
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

CORE = SRC / "gateway"
CONTROL_PKG = SRC / "runtime" / "sensing" / "control"
FLEET = SRC / "site" / "fleet"

#: Other-domain tops that core production code must never import (S1).
SLICE_TOPS = (
    "control",
    "fleet",
    "bringup",
    "navigation",
    "emotion",
    "omx_adapter",
    "games",
)

#: Workspace ROS package name for every intra-tree import top we care about.
TOP_TO_PACKAGE = {
    "control": "control",
    "core_common": "core_common",
    "core_events": "core_events",
    "core_features": "core_features",
    "core_api_web": "core_api_web",
    "core": "core",
    "fleet": "fleet",
    "bringup": "bringup",
    "led": "led",
    "interfaces": "interfaces",
    "navigation": "navigation",
    "emotion": "emotion",
    "games": "games",
    "omx_adapter": "omx_adapter",
}

FINAL_CMD_VEL = re.compile(r"""['"]cmd_vel['"]""")

#: The single pinned legacy exception to guard 2: the legacy comparison
#: graph's final publisher default (see test_os_control_graph.py, which pins
#: safety_node as the legacy final publisher). Everything else in control
#: must not name the final topic.
LEGACY_FINAL_PUBLISHER = (
    "runtime/sensing/control/safety/node.py",
    "self.declare_parameter('cmd_out', 'cmd_vel')",
)


def _prod_py_files(tree: Path):
    return [
        p
        for p in tree.rglob("*.py")
        if "test" not in p.parts and "/tools/" not in p.as_posix()
    ]


def _import_tops(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def test_core_imports_no_slice_code():
    """Guard 1 (S1): no slice imports in core production code.

    ``control`` sits at ``src/runtime/sensing`` and imports itself. That package
    is not the core gateway importing a slice.
    """
    control_root = (SRC / "runtime" / "sensing").resolve()
    violations = []
    for path in _prod_py_files(CORE):
        if control_root in path.resolve().parents:
            continue
        hits = _import_tops(path) & set(SLICE_TOPS)
        if hits:
            violations.append(f"{path.relative_to(SRC)} imports {sorted(hits)}")
    assert violations == [], violations


def test_control_has_no_final_cmd_vel():
    """Guard 2 (S2): control runtime never names the final topic.

    'cmd_vel_raw' and '/cmd_vel_raw' are allowed; only the exact final
    topic string is forbidden. The one exception is the pinned legacy
    comparison-graph publisher default (LEGACY_FINAL_PUBLISHER).
    """
    forbidden_patterns = [
        FINAL_CMD_VEL,
        re.compile(r"['\"]/robot/state/.*?['\"]"),
        re.compile(r"['\"]/robot/intent/.*?['\"]"),
    ]
    violations = []
    for path in _prod_py_files(CONTROL_PKG):
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in forbidden_patterns):
                if rel == LEGACY_FINAL_PUBLISHER[0] and line.strip() == LEGACY_FINAL_PUBLISHER[1]:
                    continue
                violations.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert violations == [], violations


def _package_declared_deps(package_xml: Path):
    root = ET.parse(package_xml).getroot()
    return {
        (e.text or "").strip()
        for e in root
        if e.tag in ("depend", "exec_depend", "build_depend")
        and (e.text or "").strip()
    }


def test_package_xml_covers_imports():
    """Guard 3: every intra-tree import a package uses is declared.

    Covers Python (all packages) and C++ #includes of workspace interface
    packages (hardware C++ nodes).
    """
    violations = []
    for package_xml in sorted(SRC.rglob("package.xml")):
        pkg_dir = package_xml.parent
        declared = _package_declared_deps(package_xml)
        try:
            own_name = ET.parse(package_xml).getroot().findtext("name")
        except ET.ParseError:
            continue
        for path in _prod_py_files(pkg_dir):
            for top in _import_tops(path):
                need = TOP_TO_PACKAGE.get(top)
                if need and need != own_name and need not in declared:
                    violations.append(
                        f"{path.relative_to(SRC)} imports {top} "
                        f"but {own_name}/package.xml lacks it"
                    )
        for path in list(pkg_dir.rglob("*.cpp")) + list(pkg_dir.rglob("*.hpp")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"#include\s*[<\"](\w+)[/\"]", text):
                need = TOP_TO_PACKAGE.get(match.group(1))
                if need and need != own_name and need not in declared:
                    violations.append(
                        f"{path.relative_to(SRC)} includes {match.group(1)} "
                        f"but {own_name}/package.xml lacks it"
                    )
    assert violations == [], violations


def _publisher_calls(text):
    """Yield the full parenthesized text of each create_publisher(...) call."""
    calls = []
    for match in re.finditer(r"create_publisher\s*\(", text):
        depth = 0
        for i in range(match.end() - 1, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    calls.append(text[match.start() : i + 1])
                    break
    return calls


def test_cmd_vel_single_publisher():
    """Guard 4 (D-2): the final cmd_vel publisher lives in one place."""
    publishers = []
    for path in _prod_py_files(SRC):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for call in _publisher_calls(text):
            if "Twist" in call and FINAL_CMD_VEL.search(call):
                line = text[: text.index(call)].count("\n") + 1
                publishers.append(f"{path.relative_to(SRC).as_posix()}:{line}")
    assert len(publishers) == 1, publishers
    assert publishers[0].startswith("runtime/gateway/core/bridge/ros_bridge.py:"), publishers


def test_fleet_prod_only_core_common():
    """Guard 5 (S3): fleet production code touches core_common at most."""
    violations = []
    for path in _prod_py_files(FLEET):
        for top in _import_tops(path):
            if top.startswith("core_") and top != "core_common":
                violations.append(f"{path.relative_to(SRC)} imports {top}")
    assert violations == [], violations

def test_control_imports_no_core_code():
    """Guard 4 (D-155): control runtime never imports core.

    The control application is a plugin that is loaded by core. It must not
    statically import core_features, core_api_web, core, etc.
    """
    violations = []
    core_tops = {"core", "core_features", "core_api_web", "core_events", "core_common"}
    for path in _prod_py_files(CONTROL_PKG.parent):
        tops = _import_tops(path)
        bad = tops & core_tops
        if bad:
            rel = path.relative_to(SRC).as_posix()
            violations.append(f"{rel}: imported {', '.join(sorted(bad))}")
    assert not violations, "control must not depend on core:\n" + "\n".join(violations)




def test_games_imports_isolation():
    """Guard 6 (D-160): games runtime never imports core, rclpy, httpx, cv2.

    The games application must remain decoupled from the ROS graph (rclpy),
    the robot core (core), the fleet server (fleet), and network/vision
    hardware libraries (httpx, cv2) except where explicitly allowed (e.g. host).
    """
    violations = []
    forbidden_tops = {"core", "fleet", "rclpy", "httpx", "cv2"}
    games_src = SRC / "site" / "games" / "games"
    for path in _prod_py_files(games_src):
        # Only field, game, policy are strictly pure
        parts = path.relative_to(games_src).parts
        if not parts:
            continue
        domain = parts[0]
        if domain in ("field", "game", "policy"):
            tops = _import_tops(path)
            bad = tops & forbidden_tops
            if bad:
                rel = path.relative_to(SRC).as_posix()
                violations.append(f"{rel}: imported {', '.join(sorted(bad))}")
    assert not violations, "games pure domains must not depend on forbidden libs:\n" + "\n".join(violations)
