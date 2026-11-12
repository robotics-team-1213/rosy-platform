"""YAML-backed Staging Bays (임시칸) and Export/Takeout Stations (반출대) registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

DEFAULT_YAML_PATH = Path(__file__).with_name("station_zones.yaml")


def load_station_zones(override_path: Path | None = None) -> dict[str, Any]:
    """Load station zones (staging_bays + export_stations) from override or default YAML."""
    path = override_path if (override_path and override_path.is_file()) else DEFAULT_YAML_PATH
    raw_text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw_text) or {}
    staging = list(parsed.get("staging_bays") or [])
    exports = list(parsed.get("export_stations") or [])
    by_id: dict[str, dict[str, Any]] = {}
    for item in staging + exports:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = dict(item)
    return {
        "schema": parsed.get("schema", "rosy.station-zones.v1"),
        "site_id": parsed.get("site_id", "world_261026"),
        "staging_bays": staging,
        "export_stations": exports,
        "zones_by_id": by_id,
        "yaml_text": raw_text,
        "source_path": str(path),
    }


def save_station_zones_yaml(yaml_text: str, target_path: Path) -> dict[str, Any]:
    """Validate and persist updated YAML text for staging bays and export stations."""
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a mapping")
    if "staging_bays" not in parsed and "export_stations" not in parsed:
        raise ValueError("YAML must define staging_bays or export_stations")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml_text, encoding="utf-8")
    return load_station_zones(target_path)
