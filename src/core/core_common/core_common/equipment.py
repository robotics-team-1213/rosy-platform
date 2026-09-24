"""현장 장비 목록. 로봇에 붙은 것과 현장에 있는 것을 한 문서에 적되 섞지 않는다.

패키지를 옮기지 않는다. Pinky 바퀴는 로봇 첨부이고, 신호등과 ESP는 현장 장비다.
"""

from __future__ import annotations

from dataclasses import dataclass

from core_common.intent import IntentError, loads

ROBOT_KINDS = frozenset({"drive", "range", "imu", "lidar", "lamp", "arm"})
SITE_KINDS = frozenset({"signal", "esp", "site"})
BUSES = frozenset({"uart", "i2c", "gpio", "usb", "http"})


@dataclass(frozen=True)
class Equipment:
    id: str
    kind: str
    bus: str
    path: str | None = None
    attached_to: str | None = None


@dataclass(frozen=True)
class Catalog:
    robots: dict[str, tuple[Equipment, ...]]
    site: tuple[Equipment, ...]


def parse_catalog(text: str) -> Catalog:
    return catalog_from(loads(text))


def catalog_from(document: dict) -> Catalog:
    if not isinstance(document, dict):
        raise IntentError("NOT_A_DOCUMENT", "equipment document must be an object")
    unknown = set(document) - {"robots", "site"}
    if unknown:
        raise IntentError("UNKNOWN_FIELD", ", ".join(sorted(unknown)))
    robots_raw = document.get("robots") or {}
    site_raw = document.get("site") or []
    if not isinstance(robots_raw, dict) or not isinstance(site_raw, list):
        raise IntentError("NOT_A_DOCUMENT", "robots is an object and site is a list")
    robots = {name: tuple(_robot_item(name, item) for item in _as_list(items, name))
              for name, items in robots_raw.items()}
    site = tuple(_site_item(item) for item in site_raw)
    _links(site)
    return Catalog(robots, site)


def _as_list(items: object, name: str) -> list:
    if not isinstance(items, list):
        raise IntentError("NOT_A_LIST", f"robots.{name} is a list of attachments")
    return items


def _robot_item(robot: str, item: object) -> Equipment:
    eq = _item(item, ROBOT_KINDS, f"robots.{robot}")
    if eq.attached_to is not None:
        raise IntentError("ATTACHED_ON_ROBOT", f"{eq.id} is already on {robot}")
    return eq


def _site_item(item: object) -> Equipment:
    return _item(item, SITE_KINDS, "site")


def _item(item: object, allowed: frozenset[str], where: str) -> Equipment:
    if not isinstance(item, dict):
        raise IntentError("NOT_AN_ITEM", f"{where} entries are objects")
    unknown = set(item) - {"id", "kind", "bus", "path", "attached_to"}
    if unknown:
        raise IntentError("UNKNOWN_FIELD", ", ".join(sorted(unknown)))
    ident = item.get("id")
    kind = item.get("kind")
    bus = item.get("bus")
    if not isinstance(ident, str) or not ident:
        raise IntentError("MISSING", f"{where} needs an id")
    if kind not in allowed:
        raise IntentError("WRONG_PLACE", f"{ident} kind {kind} does not belong in {where}")
    if bus not in BUSES:
        raise IntentError("UNKNOWN_BUS", f"{ident} bus {bus}")
    path = item.get("path")
    attached = item.get("attached_to")
    if path is not None and not isinstance(path, str):
        raise IntentError("MISSING", f"{ident} path must be a string")
    if attached is not None and not isinstance(attached, str):
        raise IntentError("MISSING", f"{ident} attached_to must be a string")
    if bus == "http" and not path:
        raise IntentError("MISSING", f"{ident} http bus needs a path")
    return Equipment(ident, kind, bus, path, attached)


def _links(site: tuple[Equipment, ...]) -> None:
    ids = [item.id for item in site]
    if len(ids) != len(set(ids)):
        raise IntentError("DUPLICATE", "site equipment id is repeated")
    known = set(ids)
    for item in site:
        if item.attached_to is None:
            continue
        if item.kind != "esp":
            raise IntentError("NOT_AN_ATTACHMENT", f"only an esp board names attached_to, not {item.id}")
        if item.attached_to not in known:
            raise IntentError("UNKNOWN_EQUIPMENT", f"{item.id} attaches to unknown {item.attached_to}")
