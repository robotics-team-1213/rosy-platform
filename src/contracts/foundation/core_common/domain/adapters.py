"""YAML-only adapter registry. CORE must not import omx_adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


@dataclass(frozen=True)
class AdapterManifest:
    id: str
    version: str = "0.1.0"
    device_type: str = ""
    enabled: bool = True
    provides: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "AdapterManifest":
        raw = dict(data or {})
        adapter_id = str(raw.get("id") or "").strip()
        if not adapter_id:
            raise ValueError("adapter manifest requires id")
        provides = raw.get("provides") or ()
        return cls(
            id=adapter_id,
            version=str(raw.get("version") or "0.1.0"),
            device_type=str(raw.get("device_type") or ""),
            enabled=bool(raw.get("enabled", True)),
            provides=tuple(str(item) for item in provides),
        )


class AdapterRegistry:
    def __init__(self, items: Sequence[AdapterManifest] = ()) -> None:
        self._items = tuple(items)

    @classmethod
    def from_paths(cls, paths: Iterable[Any]) -> "AdapterRegistry":
        items: list[AdapterManifest] = []
        for path in paths:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            if not isinstance(data, Mapping):
                raise ValueError(f"adapter manifest must be a mapping: {path}")
            items.append(AdapterManifest.from_mapping(data))
        return cls(items)

    def enabled(self) -> list[AdapterManifest]:
        return [item for item in self._items if item.enabled]
