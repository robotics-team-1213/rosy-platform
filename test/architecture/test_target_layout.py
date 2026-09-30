"""D-310 source layout: product packages move; ROS package names do not."""

from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Existing path -> D-310 target path. The target is required in this move batch.
TARGET = {
    "contracts/interfaces": "contracts/interfaces",
    "contracts/foundation": "contracts/foundation",
    "runtime/gateway": "runtime/gateway",
    "runtime/services": "runtime/services",
    "runtime/events": "runtime/events",
    "runtime/sensing": "runtime/sensing",
    "runtime/api_web": "runtime/api_web",
    "runtime/navigation": "runtime/navigation",
    "devices/pinky_pro/bringup": "products/pinky_pro/bringup",
    "devices/pinky_pro/adc": "products/pinky_pro/adc",
    "devices/pinky_pro/lamp": "products/pinky_pro/lamp",
    "devices/pinky_pro/led": "products/pinky_pro/led",
    "devices/common/imu_bno055": "drivers/imu_bno055",
    "devices/omx/adapter": "products/omx/adapter",
    "products/pinky_pro": "products/pinky_pro/profile",
    "products/omx": "products/omx/profile",
    "hmi/face": "hmi/face",
    "hmi/web_common": "hmi/web_common",
    "hmi/dashboard": "hmi/dashboard",
    "hmi/pilot": "hmi/pilot",
    "site/fleet": "site/fleet",
    "site/games": "site/games",
    "site/site_vision": "site/site_vision",
    "sim/description": "sim/description",
    "sim/gz_sim": "sim/gz_sim",
    "sim/isaac_sim": "sim/isaac_sim",
}

TARGET_DOMAINS = {"contracts", "runtime", "drivers", "products", "hmi", "site", "sim"}

MOVED_PACKAGE_NAMES = {
    "devices/pinky_pro/bringup": "bringup",
    "devices/pinky_pro/adc": "sensor_adc",
    "devices/pinky_pro/lamp": "lamp_control",
    "devices/pinky_pro/led": "led",
    "devices/common/imu_bno055": "imu_bno055",
    "devices/omx/adapter": "omx_adapter",
    "products/pinky_pro": "pinky_pro",
    "products/omx": "omx",
}

PRODUCT_PACKAGES = {
    "pinky_pro": {
        "profile": "pinky_pro",
        "bringup": "bringup",
        "adc": "sensor_adc",
        "lamp": "lamp_control",
        "led": "led",
    },
    "omx": {"profile": "omx", "adapter": "omx_adapter"},
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


def test_every_package_has_a_declared_target():
    assert sorted(_packages() - set(TARGET.values())) == []


def test_xml_package_names_are_unique():
    duplicates = {name: paths for name, paths in _package_locations().items() if len(paths) != 1}
    assert duplicates == {}


def test_moved_packages_keep_their_name_at_the_exact_target():
    locations = _package_locations()
    for current, name in MOVED_PACKAGE_NAMES.items():
        target = TARGET[current]
        assert locations.get(name) == [target], (name, locations.get(name), target)
        assert not (SRC / current / "package.xml").exists(), current
        assert target.split("/")[0] in TARGET_DOMAINS, target


def test_each_package_sits_where_the_phase_allows():
    packages = _packages()
    for target in TARGET.values():
        assert target in packages, target


def test_product_containers_hold_only_the_declared_packages():
    for product, expected in PRODUCT_PACKAGES.items():
        root = SRC / "products" / product
        assert not (root / "package.xml").exists(), product
        found = {
            path.parent.relative_to(root).as_posix(): ET.parse(path).getroot().findtext("name")
            for path in root.rglob("package.xml")
        }
        assert found == expected, (product, found)
        assert (root / "profile" / "config").is_dir(), product


def test_sketch_places_outside_d231_do_not_appear():
    found = [
        path.relative_to(ROOT).as_posix()
        for path in SRC.rglob("*")
        if path.is_dir() and path.name in FORBIDDEN_NAMES
    ]
    assert found == []
