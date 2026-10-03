"""D-149 / D-168: what control actually runs on the robot, and who provides core's sensors.

The deployed launch closure is walked from the systemd units and compose file
through every launch include, so the set of control executables is derived,
not remembered. D-149 once listed three executables while the closure ran
four (road_observer_node) — this test exists so that record cannot drift again.

Honest holes, not oversights:
- Includes are found by launch file name (``*.launch.py`` / ``*_launch.xml``)
  anywhere in a launch file's text. Mentioning a file name in a comment pulls it
  into the closure: that errs toward a larger closure, never a smaller one.
- Launch names not found under the colcon roots are treated as third-party and not walked.
- An executable chosen at runtime (a LaunchConfiguration as ``executable=``)
  is invisible.
"""

import re
from pathlib import Path

from robot_contracts import COLCON_ROOTS, DEPLOY, LAUNCH_REFERENCE, ROOT

SRC = ROOT / "src"

#: colcon output. CI builds at the repo root now (D-427), but a local build run
#: inside a colcon root copies every launch file and setup.py there; counting
#: those makes each name "ambiguous" and the provider look registered twice.
COLCON_OUTPUT = {"build", "install", "log"}

#: A walk that finds nothing would pass every closure check; refuse it. Today: 37
#: non-test launch files (`*.launch.py`, `*_launch.xml`, ...) under the roots.
MIN_LAUNCH_FILES = 37  # update when a launch file is legitimately removed


def _source_files(pattern: str):
    """(path, parts relative to its colcon root) for each match outside hidden and colcon-output paths."""
    for root in COLCON_ROOTS:
        for path in sorted((ROOT / root).rglob(pattern)):
            parts = path.relative_to(ROOT / root).parts
            if parts and parts[0] in COLCON_OUTPUT:
                continue
            if any(p.startswith(".") for p in parts):
                continue
            yield path, parts

#: D-143 evidence producers. They publish observations, never a velocity command.
DEPLOYED_CONTROL_EXECUTABLES = {
    "ir_adc_node",
    "camera_detect_node",
    "line_observer_node",
    "road_observer_node",
    # D-373: shadow-only learned lane evidence and the capture trigger, both in
    # camera_preview.launch.py behind switches that default off. Neither
    # publishes a velocity command (learned output is never read by driving).
    "learned_lane_node",
    "capture_trigger_node",
    # D-395 P2-3: localization state, candidates and the checked initialpose; in the
    # closure through hardware.launch.py behind enable_loc_assist (default off on
    # the device). It publishes no velocity command.
    "loc_assist_node",
    # D-411 A: Pilot learning recording, always started by camera_preview.launch.py and
    # idle until CORE asks. Evidence only; it publishes no velocity command.
    "pilot_recorder_node",
    # D-423: advisory object detection on vision/detections, in camera_preview.launch.py
    # behind object_det (ROSY_OBJECT_DET, default off). CORE does not read it (D-137).
    "object_detector_node",
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
    for path, parts in _source_files("*"):
        if not path.is_file() or "test" in parts:
            continue
        if LAUNCH_REFERENCE.fullmatch(path.name):
            index.setdefault(path.name, []).append(path)
    assert sum(map(len, index.values())) >= MIN_LAUNCH_FILES, index
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
    """D-149 Validation (corrected 2026-09-22): the evidence producers, no final publisher."""
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
    setup = (SRC / "runtime" / "sensing" / "setup.py").read_text(encoding="utf-8")
    missing = [exe for exe in DEPLOYED_CONTROL_EXECUTABLES if f"'{exe} =" not in setup and f'"{exe} =' not in setup]
    assert missing == [], missing


def test_exactly_one_package_provides_core_sensors():
    """D-126: core resolves the provider by name and loads matches[0].

    Two registrants would make core pick one silently, so a package split that
    moves the provider must delete the old entry point in the same change.
    """
    registrants = []
    for path, _ in [*_source_files("setup.py"), *_source_files("setup.cfg")]:
        text = path.read_text(encoding="utf-8")
        block = re.search(re.escape(PROVIDER_GROUP) + r"['\"]?\s*[:=]\s*\[?(.*?)(\]|\n\S)", text, re.S)
        if block and re.search(r"\b" + PROVIDER_NAME + r"\s*=", block.group(1)):
            registrants.append(path.relative_to(ROOT).as_posix())
    assert registrants == ["src/runtime/sensing/setup.py"], registrants
