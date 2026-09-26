"""Boot stage model shared by the boot indicator (D-174 T0) and the black box (D-175 L1)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "deploy/robot/native/rosy_boot_state.py"
    spec = importlib.util.spec_from_file_location("rosy_boot_state", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ALL_ACTIVE = {
    "rosy-release-recover.service": "active",
    "rosy-first-boot.service": "active",
    "rosy-sd-provision.service": "active",
    "rosy-core.service": "active",
    "rosy-runtime.target": "active",
}


def test_everything_active_is_core_ready():
    stage = _module().classify(ALL_ACTIVE, {"state": "PROVISIONED"})

    assert stage.name == "CORE_READY"
    assert stage.failed_unit is None
    assert stage.label == "CORE_READY"


def test_the_first_card_failure_is_reported_as_the_recovery_gate():
    # The first Pinky boot: recovery failed, so core and the target never started.
    units = dict(ALL_ACTIVE)
    units["rosy-release-recover.service"] = "failed"
    units["rosy-core.service"] = "inactive"
    units["rosy-runtime.target"] = "inactive"

    stage = _module().classify(units, {"state": "PROVISIONED"})

    assert stage.name == "FAILED"
    assert stage.failed_unit == "rosy-release-recover.service"
    assert stage.label == "FAILED:rosy-release-recover"


def test_the_earliest_failed_unit_in_boot_order_wins():
    units = dict(ALL_ACTIVE)
    units["rosy-core.service"] = "failed"
    units["rosy-first-boot.service"] = "failed"

    stage = _module().classify(units, {"state": "PROVISIONED"})

    assert stage.failed_unit == "rosy-first-boot.service"


def test_moved_card_setup_is_reported_before_the_expected_first_boot_failure():
    units = dict(ALL_ACTIVE)
    units["rosy-first-boot.service"] = "failed"
    units["rosy-core.service"] = "inactive"
    stage = _module().classify(units, {"state": "NEW_DEVICE_SETUP", "reason": "hardware_changed"})
    assert stage.name == "SETUP"
    assert stage.label == "SETUP"
    assert stage.detail == "new device registration required"


@pytest.mark.parametrize("state", ["PROVISIONING_AP", "PROVISIONING_HOLD"])
def test_a_held_personalization_is_a_failure_with_its_reason(state):
    units = dict(ALL_ACTIVE, **{"rosy-core.service": "inactive", "rosy-runtime.target": "inactive"})

    stage = _module().classify(units, {"state": state, "reason": "site_wifi_unreachable"})

    assert stage.name == "FAILED"
    assert stage.failed_unit == "rosy-first-boot.service"
    assert stage.detail == f"{state}: site_wifi_unreachable"


def test_provisioned_while_core_is_still_starting():
    units = dict(ALL_ACTIVE, **{"rosy-core.service": "activating", "rosy-runtime.target": "inactive"})

    stage = _module().classify(units, {"state": "PROVISIONED"})

    assert stage.name == "PROVISIONED"


@pytest.mark.parametrize("provisioning", [None, {"state": "APPLYING"}])
def test_anything_earlier_is_booting(provisioning):
    units = {unit: "activating" for unit in ALL_ACTIVE}

    stage = _module().classify(units, provisioning)

    assert stage.name == "BOOTING"


def test_unknown_or_missing_units_are_never_ready():
    stage = _module().classify({"rosy-core.service": "active"}, {"state": "PROVISIONED"})

    assert stage.name != "CORE_READY"


def test_the_model_uses_only_the_standard_library():
    source = (ROOT / "deploy/robot/native/rosy_boot_state.py").read_text(encoding="utf-8")

    assert "rclpy" not in source and "import core" not in source
