"""A Pinky Pro device CORE watches its front, not its rear (D-344 §11, D-47 addendum).

rplidar_link is yaw pi on base_link, so the line-follow obstacle sector must be
centred on scan angle 180. rosy_default.yaml keeps the generic 0; the Pinky Pro
robot package's config/core.yaml carries 180. These tests load the config the
way rosy-core.service does: the image's runtime.env, ROSY_DEPLOYMENT=device, no
ROSY_CONFIG, HOME=/var/lib/rosy/core with the first-boot overlay (card
credential only) in ~/.rosy/rosy.yaml.
"""
import math
import sys
import types
from pathlib import Path

import pytest
import yaml

from core.lidar_mount import resolve_lidar_forward_deg
from core.services import _line_follow_config
from core_common import config as config_module
from core_common.calibration_store import CalibrationStore
from core_common.config import load_config
from core_common.profile import robot_config_dir

REPO = Path(__file__).resolve().parents[4]
RUNTIME_ENV = REPO / "deploy" / "robot" / "pinky_pro" / "native" / "rosy-runtime.env"
DEFAULT = REPO / "contracts" / "foundation" / "config" / "rosy_default.yaml"


@pytest.fixture(autouse=True)
def no_ament_share(monkeypatch):
    """ament importable but knowing no package, so the source tree decides: a stale
    installed pinky_pro (or core_common) share on a sourced ROS box cannot leak in."""
    package = types.ModuleType("ament_index_python")
    packages = types.ModuleType("ament_index_python.packages")

    class PackageNotFoundError(KeyError):
        pass

    def missing(name):
        raise PackageNotFoundError(name)

    packages.PackageNotFoundError = PackageNotFoundError
    packages.get_package_share_directory = missing
    package.packages = packages
    monkeypatch.setitem(sys.modules, "ament_index_python", package)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", packages)


def _device_env(monkeypatch):
    for name in ("ROSY_CONFIG", "ROSY_ROBOT", "ROSY_DEV_AUTH", "ROSY_DEVICE_NAME"):
        monkeypatch.delenv(name, raising=False)
    for line in RUNTIME_ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, value = line.partition("=")
            monkeypatch.setenv(name.strip(), value.strip())
    # First boot fills the identity fields of /etc/rosy/runtime.env.
    monkeypatch.setenv("ROSY_NAMESPACE", "rosy_18")
    monkeypatch.setenv("ROSY_ROBOT_NUMBER", "18")


def _first_boot_overlay(tmp_path, extra=None):
    overlay = {"auth": {"tokens": [{"id": "card-0001", "role": "administrator",
                                    "sha256": "0" * 64, "source": "card"}]}}
    overlay.update(extra or {})
    path = tmp_path / ".rosy" / "rosy.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(overlay), encoding="utf-8")
    return path


def test_pinky_pro_device_core_line_follow_watches_the_front(monkeypatch, tmp_path):
    _device_env(monkeypatch)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", _first_boot_overlay(tmp_path))
    assert config_module._find_default_config() == DEFAULT
    assert robot_config_dir("pinky_pro") == REPO / "middleware" / "apps" / "device" / "pinky" / "profile" / "config"
    config = load_config()
    assert config["robot"]["model"] == "pinky_pro"
    assert config["runtime"]["deployment"] == "device"
    assert config["line_follow"]["lidar_forward_deg"] == 180.0
    # What CORE actually uses: services parse, then node.py's resolver with no accepted mount.
    parsed = _line_follow_config(config["line_follow"])
    assert parsed.lidar_forward_deg == 180.0
    deg, source, _ = resolve_lidar_forward_deg(config["line_follow"], hand_default=parsed.lidar_forward_deg,
                                               store=CalibrationStore(tmp_path / "store"), robot="rosy_18")
    assert deg == 180.0 and "hand value" in source


def test_generic_default_is_unchanged():
    assert yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["line_follow"]["lidar_forward_deg"] == 0.0


def test_operator_overlay_still_wins(monkeypatch, tmp_path):
    _device_env(monkeypatch)
    overlay = _first_boot_overlay(tmp_path, {"line_follow": {"lidar_forward_deg": 182.0}})
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", overlay)
    assert load_config()["line_follow"]["lidar_forward_deg"] == 182.0


def test_order_urdf_nominal_then_record_then_operator_overlay(monkeypatch, tmp_path):
    """D-397: core.yaml's URDF nominal 180 < an accepted lidar_mount record < the operator overlay."""
    from core_common.config import local_overlay
    _device_env(monkeypatch)
    store = CalibrationStore(tmp_path / "store")

    def resolved():
        config = load_config()
        operator = (local_overlay().get("line_follow") or {}).get("lidar_forward_deg")
        return resolve_lidar_forward_deg(config["line_follow"], hand_default=0.0, store=store,
                                         robot="rosy_18", operator_deg=operator)

    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", _first_boot_overlay(tmp_path))
    deg, source, _ = resolved()
    assert deg == 180.0 and "hand value" in source
    rid = store.add("rosy_18", "lidar_mount", {"lidar_yaw_offset": math.radians(181.9)}, method="t/1")
    store.set_status("rosy_18", "lidar_mount", rid, "accepted", actor="operator")
    deg, source, _ = resolved()
    assert deg == pytest.approx(181.9) and rid in source
    overlay = tmp_path / "op" / "rosy.yaml"
    overlay.parent.mkdir()
    overlay.write_text(yaml.safe_dump({"line_follow": {"lidar_forward_deg": 183.0}}), encoding="utf-8")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", overlay)
    deg, source, warn = resolved()
    assert deg == 183.0 and "operator overlay" in source and warn is False


@pytest.mark.parametrize("how", ["env", "overlay"])
def test_other_robot_packages_keep_the_generic_value(monkeypatch, tmp_path, how):
    _device_env(monkeypatch)
    extra = {}
    if how == "env":
        monkeypatch.setenv("ROSY_ROBOT", "omx")
    else:
        extra = {"robot": {"model": "omx"}}
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", _first_boot_overlay(tmp_path, extra))
    assert load_config()["line_follow"]["lidar_forward_deg"] == 0.0
