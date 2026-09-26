from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "omx"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, OMX / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


inventory_module = load("omx_multi_inventory", "host_inventory.py")
preflight = load("omx_multi_preflight", "preflight.py")


def inventory(*, second_host: str = "site_pc_01", second_enabled: bool = True):
    return inventory_module.load_inventory(
        "schema: rosy.omx-host-inventory.v1\n"
        "site_id: site_01\n"
        "hosts:\n  site_pc_01: {}\n  site_pc_02: {}\n"
        "workcells:\n"
        "  omx_01:\n"
        "    instance_id: omx_01_control\n"
        "    host_id: site_pc_01\n"
        "    enabled: true\n"
        "    follower: /dev/serial/by-id/follower-01\n"
        "    leader: /dev/serial/by-id/leader-01\n"
        "  omx_02:\n"
        "    instance_id: omx_02_control\n"
        f"    host_id: {second_host}\n"
        f"    enabled: {str(second_enabled).lower()}\n"
        "    follower: /dev/serial/by-id/follower-02\n"
        "    leader: /dev/serial/by-id/leader-02\n"
    )


def probe(
    selections: dict[str, str],
    *,
    denied: set[str] | None = None,
    missing: set[str] | None = None,
):
    calls = []
    denied = denied or set()
    missing = missing or set()

    def realpath(path):
        calls.append(path)
        return selections[path]

    def stat_fn(path):
        if path in missing:
            raise FileNotFoundError(path)
        return type("Stat", (), {"st_mode": stat.S_IFCHR | 0o600})()

    def access_fn(path, mode):
        return path not in denied

    return (realpath, stat_fn, access_fn), calls


SELECTIONS = {
    "/dev/serial/by-id/follower-01": "/dev/ttyUSB0",
    "/dev/serial/by-id/leader-01": "/dev/ttyUSB1",
    "/dev/serial/by-id/follower-02": "/dev/ttyUSB2",
    "/dev/serial/by-id/leader-02": "/dev/ttyUSB3",
}


def test_two_enabled_workcells_get_only_their_own_verified_paths():
    fake_probe, calls = probe(SELECTIONS)
    resolved = preflight.resolve_host_devices(inventory(), "site_pc_01", probe=fake_probe)
    assert resolved == {
        "omx_01": {"OMX_FOLLOWER_DEVICE": "/dev/ttyUSB0", "OMX_LEADER_DEVICE": "/dev/ttyUSB1"},
        "omx_02": {"OMX_FOLLOWER_DEVICE": "/dev/ttyUSB2", "OMX_LEADER_DEVICE": "/dev/ttyUSB3"},
    }
    assert set(calls) == set(SELECTIONS)


def test_disabled_and_other_host_devices_are_not_probed_or_reserved():
    fake_probe, calls = probe(SELECTIONS)
    assert preflight.resolve_host_devices(
        inventory(second_enabled=False), "site_pc_01", probe=fake_probe
    ) == {
        "omx_01": {"OMX_FOLLOWER_DEVICE": "/dev/ttyUSB0", "OMX_LEADER_DEVICE": "/dev/ttyUSB1"}
    }
    assert calls == ["/dev/serial/by-id/follower-01", "/dev/serial/by-id/leader-01"]

    fake_probe, calls = probe(SELECTIONS)
    assert list(preflight.resolve_host_devices(
        inventory(second_host="site_pc_02"), "site_pc_01", probe=fake_probe
    )) == ["omx_01"]
    assert len(calls) == 2


def test_aliasing_by_id_entries_on_one_host_is_rejected():
    selections = {**SELECTIONS, "/dev/serial/by-id/follower-02": "/dev/ttyUSB0"}
    fake_probe, _ = probe(selections)
    with pytest.raises(ValueError, match="omx_01.*omx_02|omx_02.*omx_01"):
        preflight.resolve_host_devices(inventory(), "site_pc_01", probe=fake_probe)


@pytest.mark.parametrize(
    ("denied", "missing", "message"),
    [
        ({"/dev/ttyUSB3"}, set(), "read/write"),
        (set(), {"/dev/ttyUSB3"}, "unavailable"),
    ],
)
def test_any_failed_workcell_refuses_the_whole_host(denied, missing, message):
    fake_probe, _ = probe(SELECTIONS, denied=denied, missing=missing)
    with pytest.raises(ValueError, match=f"omx_02.*{message}"):
        preflight.resolve_host_devices(inventory(), "site_pc_01", probe=fake_probe)


def test_unknown_host_is_rejected():
    fake_probe, calls = probe(SELECTIONS)
    with pytest.raises(ValueError, match="unknown host_id"):
        preflight.resolve_host_devices(inventory(), "unknown", probe=fake_probe)
    assert calls == []
