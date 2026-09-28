"""Parse a static OMX host inventory without probing devices or starting ROS."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml


class InventoryError(ValueError):
    """The host inventory cannot be admitted."""


@dataclass(frozen=True)
class Host:
    host_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class Workcell:
    workcell_id: str
    instance_id: str
    host_id: str
    enabled: bool
    follower: str | None
    leader: str | None
    camera: str | None


@dataclass(frozen=True)
class Inventory:
    site_id: str
    hosts: tuple[Host, ...]
    workcells: tuple[Workcell, ...]


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise InventoryError("mapping keys must be scalar") from exc
        if duplicate:
            raise InventoryError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping
)


def _boolean(_loader: _UniqueKeyLoader, node: yaml.ScalarNode) -> bool:
    if node.value not in ("true", "false"):
        raise InventoryError("boolean values must be true or false")
    return node.value == "true"


_UniqueKeyLoader.add_constructor("tag:yaml.org,2002:bool", _boolean)


_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_BY_ID_PREFIX = "/dev/serial/by-id/"


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise InventoryError(f"{label} must be a nonempty identifier")
    return value


def _allowed_fields(mapping: dict, allowed: set[str], label: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise InventoryError(f"{label} has unknown fields: {sorted(map(str, unknown))}")


def _serial(value: object, label: str, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise InventoryError(f"{label} is required for an enabled workcell")
        return None
    if not isinstance(value, str) or not value.startswith(_BY_ID_PREFIX):
        raise InventoryError(f"{label} must be a /dev/serial/by-id/ selection")
    entry = value[len(_BY_ID_PREFIX):]
    if not entry or "/" in entry or "\\" in entry or any(char.isspace() for char in entry):
        raise InventoryError(f"{label} must be a single /dev/serial/by-id/ entry")
    if any(mark in entry for mark in ("<", ">", "$", "{", "}")) or any(
        word in entry.lower() for word in ("placeholder", "example", "selected", "todo")
    ):
        raise InventoryError(f"{label} contains a placeholder")
    return value


def _camera(value: object, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(mark in value for mark in ("<", ">", "${"))
        or any(word in value.lower() for word in ("placeholder", "example", "selected", "todo"))
    ):
        raise InventoryError(f"{label} must be a selected camera identity or null")
    return value


def load_inventory(text: str) -> Inventory:
    """Validate inventory data; real device identity belongs to host preflight."""
    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise InventoryError("invalid inventory YAML") from exc
    if not isinstance(document, dict):
        raise InventoryError("inventory must be a mapping")
    _allowed_fields(document, {"schema", "site_id", "hosts", "workcells"}, "inventory")
    if document.get("schema") != "rosy.omx-host-inventory.v1":
        raise InventoryError("unsupported inventory schema")
    site_id = _identifier(document.get("site_id"), "site_id")
    host_entries = document.get("hosts")
    workcell_entries = document.get("workcells")
    if not isinstance(host_entries, dict) or not host_entries:
        raise InventoryError("hosts must be a nonempty mapping")
    if not isinstance(workcell_entries, dict) or not workcell_entries:
        raise InventoryError("workcells must be a nonempty mapping")

    hosts = []
    for raw_host_id, raw_host in host_entries.items():
        host_id = _identifier(raw_host_id, "host_id")
        if not isinstance(raw_host, dict):
            raise InventoryError(f"host {host_id} must be a mapping")
        _allowed_fields(raw_host, {"roles"}, f"host {host_id}")
        raw_roles = raw_host.get("roles", [])
        if not isinstance(raw_roles, list) or any(
            not isinstance(role, str) or not role.strip() for role in raw_roles
        ):
            raise InventoryError(f"host {host_id} roles must be a list of names")
        hosts.append(Host(host_id=host_id, roles=tuple(raw_roles)))

    host_ids = {host.host_id for host in hosts}
    instance_ids: set[str] = set()
    active_selections: dict[tuple[str, str], str] = {}
    workcells = []
    for raw_workcell_id, raw_cell in workcell_entries.items():
        workcell_id = _identifier(raw_workcell_id, "workcell_id")
        if not isinstance(raw_cell, dict):
            raise InventoryError(f"workcell {workcell_id} must be a mapping")
        _allowed_fields(
            raw_cell,
            {"instance_id", "host_id", "enabled", "follower", "leader", "camera"},
            f"workcell {workcell_id}",
        )
        instance_id = _identifier(raw_cell.get("instance_id"), "instance_id")
        if instance_id in instance_ids:
            raise InventoryError(f"duplicate instance_id: {instance_id}")
        instance_ids.add(instance_id)
        host_id = _identifier(raw_cell.get("host_id"), "host_id")
        if host_id not in host_ids:
            raise InventoryError(f"workcell {workcell_id} has unknown host_id: {host_id}")
        enabled = raw_cell.get("enabled")
        if type(enabled) is not bool:
            raise InventoryError(f"workcell {workcell_id} needs explicit boolean enabled")
        follower = _serial(raw_cell.get("follower"), "follower", required=enabled)
        leader = _serial(raw_cell.get("leader"), "leader", required=enabled)
        camera = _camera(raw_cell.get("camera"), "camera")
        if enabled:
            if follower == leader:
                raise InventoryError(f"workcell {workcell_id} needs different follower and leader")
            for label, selection in (("follower", follower), ("leader", leader), ("camera", camera)):
                if selection is None:
                    continue
                key = (host_id, selection)
                if key in active_selections:
                    raise InventoryError(
                        f"duplicate {label} selection on host {host_id}: {active_selections[key]}"
                    )
                active_selections[key] = workcell_id
        workcells.append(
            Workcell(workcell_id, instance_id, host_id, enabled, follower, leader, camera)
        )
    return Inventory(site_id, tuple(hosts), tuple(workcells))
