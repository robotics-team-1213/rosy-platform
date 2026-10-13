"""Choose a host site occupancy map, or the packaged demo map.

Nav2 map_server needs the YAML and the image it names. Hardware mode may
bind-mount /var/lib/rosy/maps. Field hardware can require the site pair and
fail closed; simulation and bench callers may keep the demo fallback.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def resolve_occupancy_map(
    preferred: str | Path,
    fallback: str | Path,
    *,
    allow_fallback: bool = True,
) -> str:
    preferred_path = Path(preferred)
    fallback_path = Path(fallback)
    if _is_loadable(preferred_path):
        return str(preferred_path)
    if not allow_fallback:
        raise ValueError(
            "site occupancy map is missing or unloadable: " f"{preferred_path}"
        )
    return str(fallback_path)


def _is_loadable(yaml_path: Path) -> bool:
    if not yaml_path.is_file():
        return False
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(data, dict):
        return False
    image = data.get("image")
    if not isinstance(image, str) or not image:
        return False
    image_path = Path(image)
    if not image_path.is_absolute():
        image_path = yaml_path.parent / image_path
    return image_path.is_file()
