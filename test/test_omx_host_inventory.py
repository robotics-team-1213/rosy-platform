from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omx_host_inventory", ROOT / "deploy" / "omx" / "host_inventory.py"
)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory_module
SPEC.loader.exec_module(inventory_module)


FOLLOWER = "/dev/serial/by-id/usb-robotis-follower-01"
LEADER = "/dev/serial/by-id/usb-robotis-leader-01"


def make_inventory(*, workcells: str, hosts: str = "  site_pc_01: {}") -> str:
    return (
        "schema: rosy.omx-host-inventory.v1\n"
        "site_id: site_01\n"
        f"hosts:\n{hosts}\n"
        f"workcells:\n{workcells}\n"
    )


def cell(
    name: str = "omx_01",
    *,
    host: str = "site_pc_01",
    enabled: str = "false",
    follower: str | None = None,
    leader: str | None = None,
    camera: str | None = None,
    instance: str | None = None,
) -> str:
    lines = [
        f"  {name}:",
        f"    instance_id: {instance or name + '_control'}",
        f"    host_id: {host}",
        f"    enabled: {enabled}",
    ]
    if follower is not None:
        lines.append(f"    follower: {follower}")
    if leader is not None:
        lines.append(f"    leader: {leader}")
    if camera is not None:
        lines.append(f"    camera: {camera}")
    return "\n".join(lines)


def test_disabled_workcell_needs_no_device_identity():
    inventory = inventory_module.load_inventory(make_inventory(workcells=cell()))
    workcell = inventory.workcells[0]
    assert (inventory.site_id, inventory.hosts[0].host_id) == ("site_01", "site_pc_01")
    assert (workcell.workcell_id, workcell.instance_id, workcell.enabled) == (
        "omx_01", "omx_01_control", False
    )
    assert (workcell.follower, workcell.leader, workcell.camera) == (None, None, None)


def test_enabled_workcells_can_share_one_host_or_split_across_hosts():
    cells = "\n".join(
        [
            cell(enabled="true", follower=FOLLOWER, leader=LEADER),
            cell(
                "omx_02", host="site_pc_01", enabled="true",
                follower="/dev/serial/by-id/usb-robotis-follower-02",
                leader="/dev/serial/by-id/usb-robotis-leader-02",
            ),
        ]
    )
    shared = inventory_module.load_inventory(make_inventory(workcells=cells))
    assert len(shared.workcells) == 2
    split = inventory_module.load_inventory(
        make_inventory(
            workcells=cells.replace(
                "    host_id: site_pc_01\n    enabled: true",
                "    host_id: site_pc_02\n    enabled: true",
                1,
            ),
            hosts="  site_pc_01: {}\n  site_pc_02: {}",
        )
    )
    assert {workcell.host_id for workcell in split.workcells} == {"site_pc_01", "site_pc_02"}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (make_inventory(workcells=cell(enabled="true")), "follower"),
        (make_inventory(workcells=cell(enabled="true", follower=FOLLOWER)), "leader"),
        (make_inventory(workcells=cell(enabled="'true'", follower=FOLLOWER, leader=LEADER)), "enabled"),
        (make_inventory(workcells=cell(enabled="yes", follower=FOLLOWER, leader=LEADER)), "true or false"),
        (make_inventory(workcells=cell(enabled="on", follower=FOLLOWER, leader=LEADER)), "true or false"),
        (make_inventory(workcells=cell(enabled="true", follower="/dev/ttyACM0", leader=LEADER)), "by-id"),
        (
            make_inventory(
                workcells=cell(enabled="true", follower="/dev/serial/by-id/<selected>", leader=LEADER)
            ),
            "placeholder",
        ),
        (make_inventory(workcells=cell(enabled="true", follower=FOLLOWER, leader=FOLLOWER)), "different"),
        (make_inventory(workcells=cell(host="unknown_pc")), "host_id"),
        (make_inventory(workcells=cell() + "\n" + cell()), "duplicate"),
        (
            make_inventory(workcells=cell() + "\n" + cell("omx_02", instance="omx_01_control")),
            "instance_id",
        ),
        (make_inventory(workcells=cell(), hosts="  site_pc_01: {}\n  site_pc_01: {}"), "duplicate"),
        (make_inventory(workcells=cell().replace("    enabled: false", "")), "enabled"),
        (make_inventory(workcells=cell(follower="/dev/ttyACM0")), "by-id"),
    ],
)
def test_inventory_rejects_invalid_or_ambiguous_values(source, message):
    with pytest.raises(inventory_module.InventoryError, match=message):
        inventory_module.load_inventory(source)


def test_active_device_identity_must_be_unique_on_same_host():
    duplicate = "\n".join(
        [
            cell(enabled="true", follower=FOLLOWER, leader=LEADER),
            cell("omx_02", enabled="true", follower=FOLLOWER, leader="/dev/serial/by-id/usb-robotis-leader-02"),
        ]
    )
    with pytest.raises(inventory_module.InventoryError, match="duplicate.*follower"):
        inventory_module.load_inventory(make_inventory(workcells=duplicate))


def test_same_selection_on_different_hosts_is_not_a_static_conflict():
    cells = "\n".join(
        [
            cell(enabled="true", follower=FOLLOWER, leader=LEADER),
            cell("omx_02", host="site_pc_02", enabled="true", follower=FOLLOWER, leader=LEADER),
        ]
    )
    inventory = inventory_module.load_inventory(
        make_inventory(workcells=cells, hosts="  site_pc_01: {}\n  site_pc_02: {}")
    )
    assert len(inventory.workcells) == 2


def test_missing_schema_or_empty_site_is_rejected():
    for source in (
        make_inventory(workcells=cell()).replace("rosy.omx-host-inventory.v1", "other"),
        make_inventory(workcells=cell()).replace("site_id: site_01", "site_id: ''"),
    ):
        with pytest.raises(inventory_module.InventoryError):
            inventory_module.load_inventory(source)


def test_inventory_records_are_immutable():
    inventory = inventory_module.load_inventory(make_inventory(workcells=cell()))
    with pytest.raises((AttributeError, TypeError)):
        inventory.workcells[0].enabled = True


def test_tracked_example_is_disabled_and_has_no_device_ids():
    source = (ROOT / "deploy" / "omx" / "host-inventory.yaml.example").read_text(encoding="utf-8")
    inventory = inventory_module.load_inventory(source)
    assert inventory.workcells
    assert all(
        not cell.enabled and cell.follower is None and cell.leader is None and cell.camera is None
        for cell in inventory.workcells
    )


def test_duplicate_selected_camera_on_one_host_is_rejected():
    cells = "\n".join(
        [
            cell(enabled="true", follower=FOLLOWER, leader=LEADER, camera="camera-01"),
            cell(
                "omx_02", enabled="true",
                follower="/dev/serial/by-id/usb-robotis-follower-02",
                leader="/dev/serial/by-id/usb-robotis-leader-02",
                camera="camera-01",
            ),
        ]
    )
    with pytest.raises(inventory_module.InventoryError, match="duplicate camera"):
        inventory_module.load_inventory(make_inventory(workcells=cells))


def test_camera_placeholder_is_not_a_selected_identity():
    source = make_inventory(
        workcells=cell(
            enabled="true", follower=FOLLOWER, leader=LEADER, camera="camera-placeholder"
        )
    )
    with pytest.raises(inventory_module.InventoryError, match="camera"):
        inventory_module.load_inventory(source)


@pytest.mark.parametrize(
    "source",
    [
        make_inventory(workcells=cell()) + "extra_field: ignored\n",
        make_inventory(workcells=cell().replace("    enabled: false", "    enabeld: false\n    enabled: false")),
        make_inventory(workcells=cell(), hosts="  site_pc_01:\n    roels: [omx_control]"),
    ],
)
def test_unknown_inventory_fields_are_rejected(source):
    with pytest.raises(inventory_module.InventoryError, match="unknown"):
        inventory_module.load_inventory(source)
