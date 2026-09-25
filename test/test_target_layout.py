"""D-231: layered source roots. Directories move; package names do not."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Flip to True in the D-231 move batch. Until then a package may sit at either path.
MOVED = False

# current directory -> target directory (package name is the last part of both).
TARGET = {
    "core/interfaces": "contracts/interfaces",
    "core/core_common": "contracts/core_common",
    "core/core": "runtime/core",
    "core/core_features": "runtime/core_features",
    "core/core_events": "runtime/core_events",
    "core/control": "runtime/control",
    "core/core_api_web": "runtime/core_api_web",
    "navigation/navigation": "runtime/navigation",
    # Devices group by family (D-196 original plan): pinky_pro board, common chips, omx arm.
    "devices/bringup": "devices/pinky_pro/bringup",
    "devices/sensor_adc": "devices/pinky_pro/sensor_adc",
    "devices/lamp_control": "devices/pinky_pro/lamp_control",
    "devices/led": "devices/pinky_pro/led",
    "devices/imu_bno055": "devices/common/imu_bno055",
    "products/omx_adapter": "devices/omx/omx_adapter",
    "face/emotion": "hmi/emotion",
    "core/web_common": "hmi/web_common",
    "site/fleet": "site/fleet",
    "site/games": "site/games",
    "sim/description": "sim/description",
    "sim/gz_sim": "sim/gz_sim",
}

TARGET_DOMAINS = {"contracts", "runtime", "devices", "products", "hmi", "site", "sim"}

# D-231 decision 4: places the owner's sketch had that this repo does not take.
FORBIDDEN_NAMES = {"rosy_pinky_pro", "rosy_decision", "rosy_ai_worker", "ai_worker", "rosy_manipulation"}


def _packages() -> set[str]:
    return {
        path.parent.relative_to(SRC).as_posix()
        for path in SRC.rglob("package.xml")
        if not {"build", "install", "log"} & set(path.parts)
    }


def test_every_package_has_a_declared_target():
    known = set(TARGET) | set(TARGET.values())
    assert sorted(_packages() - known) == []


def test_moves_keep_the_package_name():
    for current, target in TARGET.items():
        assert current.split("/")[-1] == target.split("/")[-1], (current, target)
        assert target.split("/")[0] in TARGET_DOMAINS, target


def test_each_package_sits_where_the_phase_allows():
    packages = _packages()
    for current, target in TARGET.items():
        allowed = {target} if MOVED else {current, target}
        assert len(packages & allowed) == 1, (current, target, sorted(packages & allowed))


def test_products_hold_configuration_not_packages():
    # A product may be a config-only ament package (package.xml + CMakeLists install
    # its share, D-196) with its own test/, but it carries no runtime code.
    # omx_adapter is the one code package still waiting to move to devices/omx.
    products = SRC / "products"
    waiting = products / "omx_adapter"
    code = [
        path.relative_to(ROOT).as_posix()
        for path in products.rglob("*")
        if (path.suffix in {".py", ".cpp", ".hpp"} or path.name == "setup.py")
        and "test" not in path.relative_to(products).parts
        and (MOVED or waiting not in path.parents)
    ]
    assert code == []


def test_sketch_places_outside_d231_do_not_appear():
    found = [
        path.relative_to(ROOT).as_posix()
        for path in SRC.rglob("*")
        if path.is_dir() and path.name in FORBIDDEN_NAMES
    ]
    assert found == []
