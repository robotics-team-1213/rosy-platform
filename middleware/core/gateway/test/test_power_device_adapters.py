"""Per-device power policy (D-440): what only the gateway can check.

CORE's config parsing (defaults, robot package, per-robot overlay, a malformed
block) and the bridge's DevicePowerPort adapters. The policy itself is tested in
`middleware/core/services/test/test_power_device_policy.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from core.bridge import device_power
from core.system.power import _power_config
from core_common.config import load_config
ON, REDUCED, OFF = device_power.DeviceLevel.ON, device_power.DeviceLevel.REDUCED, device_power.DeviceLevel.OFF

ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "contracts" / "foundation" / "config"


def test_shipped_defaults_keep_the_bench_switch_off():
    raw = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    cfg = _power_config(raw["power"])
    assert cfg.device_policy.enabled is False
    assert cfg.device_policy.devices == {}


def test_an_unknown_applied_level_is_sent_once_and_counts_as_a_restart():
    port, restarted = FakePort("lidar"), []
    applied = {"lidar": None}
    for _ in range(3):
        device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert port.calls == [ON] and restarted == ["lidar"]


@pytest.mark.parametrize("block", [True, {"devices": ["lidar"]}, {"devices": {"lidar": "off"}},
                                   {"enabled": "false"}, {"devices": {"lidar": {"enabled": "off"}}},
                                   {"devices": {"lidar": {"wake_ready_s": float("nan")}}}])
def test_a_malformed_block_leaves_the_policy_off_instead_of_stopping_core(block):
    cfg = _power_config({"device_policy": block})
    assert cfg.device_policy.enabled is False and cfg.device_policy.devices == {}


# --- per-robot override through the CORE overlay -----------------------------

def test_overlay_overrides_timings_and_switch_per_robot(tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    overlay.write_text(yaml.safe_dump({"power": {
        "idle_after_s": 30, "standby_after_s": 120,
        "device_policy": {"enabled": True, "devices": {"camera": {"wake_ready_s": 4.0}}}}}),
        encoding="utf-8")
    monkeypatch.setenv("ROSY_CONFIG", str(overlay))
    monkeypatch.setenv("ROSY_ROBOT", "pinky_pro")
    cfg = _power_config(load_config(str(CONFIG_DIR / "rosy_default.yaml"))["power"])
    assert (cfg.idle_after_s, cfg.standby_after_s) == (30.0, 120.0)
    assert cfg.device_policy.enabled is True
    assert cfg.device_policy.devices["camera"].wake_ready_s == 4.0
    assert cfg.device_policy.devices["camera"].standby is OFF   # the profile's facts stay


# --- adapters ------------------------------------------------------------------

class FakePort:
    def __init__(self, name, ready=True):
        self.name, self.ready, self.calls = name, ready, []

    def apply(self, level):
        self.calls.append(level)
        return self.ready


def test_reconcile_sends_nothing_while_levels_stay_on():
    port = FakePort("lidar")
    applied = {}
    for _ in range(5):
        device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port})
    assert port.calls == []


def test_reconcile_sends_once_per_change_and_retries_an_unready_service():
    port = FakePort("lidar", ready=False)
    applied = {}
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    assert port.calls == [OFF, OFF]                   # not latched while unreachable
    port.ready = True
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    assert port.calls == [OFF, OFF, OFF]


def test_reconcile_reports_the_restart_only_when_the_on_command_went_out():
    port, applied, restarted = FakePort("lidar"), {}, []
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port}, restarted=restarted.append)
    port.ready = False
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert restarted == []                            # not sent yet: nothing restarted
    port.ready = True
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert restarted == ["lidar"]


def test_service_port_treats_reduced_as_on():
    sent = []
    port = device_power.ServiceDevicePort("lidar", lambda on: sent.append(on) or True)
    port.apply(REDUCED)
    port.apply(OFF)
    assert sent == [True, False]


def test_topic_ports_share_one_latched_board():
    published = []
    board = device_power.DeviceBoard(published.append)
    device_power.TopicDevicePort("camera", board).apply(OFF)
    device_power.TopicDevicePort("perception", board).apply(REDUCED)
    assert json.loads(published[-1]) == {"camera": "off", "perception": "reduced"}


@pytest.mark.parametrize("raw,expected", [
    ('{"device": "camera", "ready": true}', ("camera", True)),
    ('{"device": "camera", "ready": "yes"}', None),
    ('{"device": "lidar", "ready": true}', None),     # only a scan confirms the LiDAR
    ("not json", None),
    ("[1]", None),
])
def test_ready_report_parsing(raw, expected):
    assert device_power.parse_ready_report(raw) == expected
