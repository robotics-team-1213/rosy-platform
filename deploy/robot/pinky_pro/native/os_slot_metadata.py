"""Pure OS-owned metadata rendering; callers own signature and inactive-mount admission."""
from __future__ import annotations

import json

from media_layout import validate_layout
from os_state_layout import COMMON, LAYOUT_FIELDS, SHARED_BINDINGS, _object, _pairs

FILES = {"etc/fstab", "etc/rosy/os-slot.json", "etc/rosy/os-media.json", "cmdline.txt"}


def _json(value) -> str:
    return json.dumps(value, sort_keys=True) + "\n"


def render_files(layout: dict, slot: str, command: str) -> dict[str, str]:
    layout = validate_layout(layout)
    if slot not in ("a", "b"):
        raise ValueError("invalid OS slot")
    if (not isinstance(command, str) or not command.isascii() or len(command) > 16384
            or "\0" in command or len(command.strip().splitlines()) != 1):
        raise ValueError("invalid kernel command line")
    tokens = command.split()
    if (sum(word.startswith("root=") for word in tokens) != 1
            or sum(word.startswith("rosy.os_layout=") for word in tokens) > 1
            or sum(word.startswith("rauc.slot=") for word in tokens) > 1):
        raise ValueError("ambiguous kernel slot identity")
    parts = {part["role"]: part for part in layout["partitions"]}
    protocol = 2 if layout["provision_role"] == "bootstrap" else 1
    descriptor = dict(schema_version=protocol, state_schema=1, slot=slot,
        root_partuuid=parts["root_" + slot]["unique_guid"], data_partuuid=parts["data"]["unique_guid"],
        provision_partuuid=parts[layout["provision_role"]]["unique_guid"])
    lines = ["# Generated fixed A/B layout; no partition auto-grow."]
    for role, point, filesystem, options, order in (
            ("root_" + slot, "/", "ext4", "defaults", 1),
            ("boot_" + slot, "/boot/firmware", "vfat", "defaults", 2),
            ("data", "/" + COMMON, "ext4", "defaults,nodev,nosuid", 2),
            (layout["provision_role"], "/run/rosy-provision-boot", "vfat", "defaults", 2)):
        lines.append(f"PARTUUID={parts[role]['unique_guid']} {point} {filesystem} {options} 0 {order}")
    for target, subpath in SHARED_BINDINGS.items():
        lines.append(f"/{COMMON}{subpath} /{target} none bind,x-systemd.requires-mounts-for=/{COMMON} 0 0")
    tokens = [word for word in tokens if not word.startswith(("rosy.os_layout=", "rauc.slot="))]
    tokens = ["root=PARTUUID=" + descriptor["root_partuuid"] if word.startswith("root=") else word for word in tokens]
    tokens.append(f"rosy.os_layout=ab-v{protocol}")
    if protocol == 2:
        tokens.append("rauc.slot=" + slot)
    return {"etc/fstab": "\n".join(lines) + "\n", "etc/rosy/os-slot.json": _json(descriptor),
            "etc/rosy/os-media.json": _json(layout), "cmdline.txt": " ".join(tokens) + "\n"}


def rebase_files(source: dict, source_layout: dict, card_layout: dict, current_slot: str) -> dict[str, str]:
    """Transform verified factory-A inputs only; never execute candidate code or perform IO."""
    if (not isinstance(source, dict) or set(source) != FILES
            or any(not isinstance(value, str) or len(value.encode("utf-8")) > 32768 for value in source.values())):
        raise ValueError("unsupported or oversized source metadata")
    source_layout, card_layout = validate_layout(source_layout), validate_layout(card_layout)
    if (source_layout["provision_role"] != "bootstrap" or card_layout["provision_role"] != "bootstrap"
            or current_slot not in ("a", "b")):
        raise ValueError("OS installation requires protocol 2 and a known current slot")
    actual_layout = validate_layout(json.loads(source["etc/rosy/os-media.json"], object_pairs_hook=_pairs))
    if actual_layout != source_layout:
        raise ValueError("source media metadata differs from authenticated image layout")
    expected = render_files(source_layout, "a", source["cmdline.txt"])
    actual = _object(source["etc/rosy/os-slot.json"].encode("utf-8"), LAYOUT_FIELDS, schema_versions=(2,))
    descriptor = json.loads(expected["etc/rosy/os-slot.json"])
    if actual != descriptor or source["etc/fstab"] != expected["etc/fstab"]:
        raise ValueError("source descriptor or fstab differs from factory A")
    tokens = source["cmdline.txt"].split()
    for prefix, value in (("root=", "root=PARTUUID=" + descriptor["root_partuuid"]),
                          ("rosy.os_layout=", "rosy.os_layout=ab-v2"), ("rauc.slot=", "rauc.slot=a")):
        if [word for word in tokens if word.startswith(prefix)] != [value]:
            raise ValueError("source kernel identity differs from factory A")
    target = "b" if current_slot == "a" else "a"
    source_parts = {p["role"]: p for p in source_layout["partitions"]}
    card_parts = {p["role"]: p for p in card_layout["partitions"]}
    if any(source_parts[role + "a"]["size_lba"] > card_parts[role + target]["size_lba"]
           for role in ("root_", "boot_")):
        raise ValueError("inactive partition is smaller than the factory payload")
    return render_files(card_layout, target, source["cmdline.txt"])
