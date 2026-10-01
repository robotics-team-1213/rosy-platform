"""SAF-002: the teleop watchdog timeout is configurable (safety.teleop_timeout_ms).

It was hard-coded to 500 ms, so the key in rosy_default.yaml did nothing. Pinky Pro
sets 300 ms in its robot package core.yaml so a command-loss stop lands inside the
D-311 G4 limit of 0.65 s (9dfk measured 0.61-0.72 s at 500 ms, 2026-10-01).
"""
from unittest import mock

import pytest

from core.teleop_config import TELEOP_TIMEOUT_MS_RANGE, teleop_timeout_ms
from core_common import config as config_module
from core_common.config import load_config
from core_features.command.arbitration import ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager

from test_pinky_lidar_forward_device import _device_env, _first_boot_overlay, no_ament_share  # noqa: F401


def test_default_is_500_and_values_are_validated():
    assert teleop_timeout_ms({}) == 500
    assert teleop_timeout_ms({"teleop_timeout_ms": 300}) == 300
    low, high = TELEOP_TIMEOUT_MS_RANGE
    for bad in (low - 1, high + 1, 250.5, "300", True, None):
        with pytest.raises(ValueError):
            teleop_timeout_ms({"teleop_timeout_ms": bad})


def test_command_manager_uses_the_configured_timeout():
    manager = CommandManager(SourceRegistry(None), ModeMachine(), safety=mock.MagicMock(),
                             teleop_timeout_ms=300)
    assert manager.watchdog.timeout_ms == 300
    manager.watchdog.refresh(10.0)
    assert not manager.watchdog.expired(10.29)
    assert manager.watchdog.expired(10.31)


def test_pinky_pro_device_core_uses_300_ms(monkeypatch, tmp_path):
    _device_env(monkeypatch)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", _first_boot_overlay(tmp_path))
    config = load_config()
    assert teleop_timeout_ms(config["safety"]) == 300
    # the robot layer must not wipe the other safety defaults
    assert "manual_linear" in config["safety"]
