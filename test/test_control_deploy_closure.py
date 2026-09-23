"""D-149 / D-168: what control actually runs on the robot, and who provides core's sensors.

The deployed launch closure is walked from the systemd units and compose file
through every launch include, so the set of control executables is derived,
not remembered. D-149 once listed three executables while the closure ran
four (road_observer_node) — this test exists so that record cannot drift again.

Honest holes, not oversights:
- Includes are found by launch file name (``*.launch.py`` / ``*_launch.xml``)
  anywhere in a launch file's text. Mentioning a file name in a comment pulls it
  into the closure: that errs toward a larger closure, never a smaller one.
- Launch names not found in ``src/`` are treated as third-party and not walked.
- An executable chosen at runtime (a LaunchConfiguration as ``executable=``)
  is invisible.
"""

import re
from pathlib import Path

from robot_contracts import DEPLOY, LAUNCH_REFERENCE, ROOT

SRC = ROOT / "src"

#: colcon output. CI builds inside the source tree (`src/build`, `src/install`),
#: which copies every launch file and setup.py; counting those makes each name
#: "ambiguous" and the provider look registered twice.
COLCON_OUTPUT = {"build", "install", "log"}


def _source_parts(path: Path) -> tuple[str, ...] | None:
    """Parts relative to `src`, or None for hidden and colcon-output paths."""
    parts = path.relative_to(SRC).parts
    if parts and parts[0] in COLCON_OUTPUT:
        return None
    if any(p.startswith(".") for p in parts):
        return None
    return parts

#: D-143 evidence producers. They publish observations, never a velocity command.
DEPLOYED_CONTROL_EXECUTABLES = {
    "ir_adc_node",
    "camera_detect_node",
    "line_observer_node",
    "road_observer_node",
}

#: Control executables that can own the final command (D-149 standalone exception).
CONTROL_FINAL_PUBLISHERS = {"safety_node"}

PROVIDER_GROUP = "rosy.sensor_provider"
PROVIDER_NAME = "control"

NODE_KWARG = re.compile(r"\b(package|executable)\s*=\s*['\"](\w+)['\"]")
XML_NODE = re.compile(r"<node\b[^>]*>", re.S)
XML_ATTR = re.compile(r"\b(pkg|exec)\s*=\s*['\"](\w+)['\"]")


def _launch_index():
    index = {}
    for path in SRC.rglob("*"):
        parts = _source_parts(path)
        if not path.is_file() or parts is None or "test" in parts:
            continue
        if LAUNCH_REFERENCE.fullmatch(path.name):
            index.setdefault(path.name, []).append(path)
    return index


def _roots():
    names = set()
    for path in [DEPLOY / "compose.yaml", *sorted((DEPLOY / "native").glob("*.service"))]:
        names.update(LAUNCH_REFERENCE.findall(path.read_text(encoding="utf-8")))
    return names


def _closure():
    index = _launch_index()
    pending, seen = list(_roots()), {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        paths = index.get(name, [])
        if not paths:
            continue  # a third-party launch (e.g. sllidar_ros2); it cannot start control
        assert len(paths) == 1, f"{name}: ambiguous launch file name {paths}"
        seen[name] = paths[0]
        pending.extend(LAUNCH_REFERENCE.findall(paths[0].read_text(encoding="utf-8")))
    return seen


def _node_calls(text: str):
    """Yield the argument text of each Node(...) call, parentheses balanced."""
    for match in re.finditer(r"\bNode\s*\(", text):
        depth = 0
        for i in range(match.end() - 1, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    yield text[match.end() : i]
                    break


def _executables(path: Path):
    text = path.read_text(encoding="utf-8")
    pairs = set()
    for call in _node_calls(text):
        kwargs = dict((k, v) for k, v in NODE_KWARG.findall(call))
        if "package" in kwargs and "executable" in kwargs:
            pairs.add((kwargs["package"], kwargs["executable"]))
    for tag in XML_NODE.findall(text):
        attrs = dict(XML_ATTR.findall(tag))
        if "pkg" in attrs and "exec" in attrs:
            pairs.add((attrs["pkg"], attrs["exec"]))
    return pairs


def test_the_closure_reaches_the_control_launch():
    closure = _closure()
    assert {"bringup_robot.launch.py", "hardware.launch.py", "line_follow.launch.py"} <= set(closure), sorted(closure)


def test_deployed_closure_runs_exactly_the_evidence_producers():
    """D-149 Validation (corrected 2026-09-22): four evidence producers, no final publisher."""
    running = {
        exe
        for path in _closure().values()
        for pkg, exe in _executables(path)
        if pkg == "control"
    }
    assert running == DEPLOYED_CONTROL_EXECUTABLES, (
        f"new: {sorted(running - DEPLOYED_CONTROL_EXECUTABLES)}, "
        f"gone: {sorted(DEPLOYED_CONTROL_EXECUTABLES - running)}"
    )
    assert not running & CONTROL_FINAL_PUBLISHERS


def test_deployed_control_executables_are_installed_entry_points():
    setup = (SRC / "apps" / "control" / "setup.py").read_text(encoding="utf-8")
    missing = [exe for exe in DEPLOYED_CONTROL_EXECUTABLES if f"'{exe} =" not in setup and f'"{exe} =' not in setup]
    assert missing == [], missing


def test_exactly_one_package_provides_core_sensors():
    """D-126: core resolves the provider by name and loads matches[0].

    Two registrants would make core pick one silently, so a package split that
    moves the provider must delete the old entry point in the same change.
    """
    registrants = []
    for path in sorted(SRC.rglob("setup.py")) + sorted(SRC.rglob("setup.cfg")):
        if _source_parts(path) is None:
            continue
        text = path.read_text(encoding="utf-8")
        block = re.search(re.escape(PROVIDER_GROUP) + r"['\"]?\s*[:=]\s*\[?(.*?)(\]|\n\S)", text, re.S)
        if block and re.search(r"\b" + PROVIDER_NAME + r"\s*=", block.group(1)):
            registrants.append(path.relative_to(SRC).as_posix())
    assert registrants == ["apps/control/setup.py"], registrants
