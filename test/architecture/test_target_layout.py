"""D-310 source layout, shrinking while D-427 moves packages out of src/.

ROS package names never change (D-231). Name preservation across every colcon root is
test_colcon_roots.py::test_ros_package_names_are_frozen, and the folder-to-name table is
test_folder_package_names.py. This file keeps the D-310 rows of the packages still under
src/; a D-427 wave that moves a package deletes its row. The D-310 product-family
containers (products/pinky_pro, products/omx) left src/ in D-427 wave 4c.
"""

from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
COLCON_ROOTS = yaml.safe_load(
    (ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))["colcon_roots"]

# Packages still under src/ (folder relative to src/). D-427 wave 4e empties it.
TARGET = {
    "runtime/sensing",
}

# D-231 decision 4: places the owner's sketch had that this repo does not take.
FORBIDDEN_NAMES = {"rosy_pinky_pro", "rosy_decision", "rosy_ai_worker", "ai_worker", "rosy_manipulation"}


def _package_locations() -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    for path in SRC.rglob("package.xml"):
        if {"build", "install", "log"} & set(path.relative_to(SRC).parts):
            continue
        name = ET.parse(path).getroot().findtext("name")
        assert name, path
        locations.setdefault(name, []).append(path.parent.relative_to(SRC).as_posix())
    return {name: sorted(paths) for name, paths in locations.items()}


def _packages() -> set[str]:
    return {path for paths in _package_locations().values() for path in paths}


def test_every_package_left_in_src_has_a_declared_row():
    assert sorted(_packages() - TARGET) == []


def test_each_row_still_holds_its_package():
    assert sorted(TARGET - _packages()) == [], "a moved package: delete its row"


def test_sketch_places_outside_d231_do_not_appear():
    found = [
        path.relative_to(ROOT).as_posix()
        for root in COLCON_ROOTS
        for path in (ROOT / root).rglob("*")
        if path.is_dir() and path.name in FORBIDDEN_NAMES
    ]
    assert found == []
