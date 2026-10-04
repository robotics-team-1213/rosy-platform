"""월드별 시뮬 숫자의 유일한 출처. ROS 무의존."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

CATALOG = Path(__file__).resolve().parent.parent / "config" / "worlds.yaml"


class WorldProfile:
    def __init__(
        self,
        world_name: str,
        map: str = "",
        inflation_radius: float = 0.0,
        spawn_x: float = 0.0,
        spawn_y: float = 0.0,
        spawn_spacing: float = 1.5,
        world_source: str = "",
    ) -> None:
        self.world_name = world_name
        self.map = map
        self.inflation_radius = inflation_radius
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y
        self.spawn_spacing = spawn_spacing
        self.world_source = world_source

    def overlay(self, **updates) -> "WorldProfile":
        payload = {
            "world_name": self.world_name,
            "map": self.map,
            "inflation_radius": self.inflation_radius,
            "spawn_x": self.spawn_x,
            "spawn_y": self.spawn_y,
            "spawn_spacing": self.spawn_spacing,
            "world_source": self.world_source,
        }
        payload.update({k: v for k, v in updates.items() if v is not None})
        return WorldProfile(**payload)


def _key(world_name: str) -> str:
    name = Path(world_name).name
    return name if name.endswith(".world") else f"{name}.world"


def load_worlds(path: Path | None = None) -> dict[str, WorldProfile]:
    catalog = path or CATALOG
    raw = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    worlds = raw.get("worlds") or {}
    if not isinstance(worlds, dict) or not worlds:
        raise ValueError(f"{catalog}: worlds mapping is required")
    out: dict[str, WorldProfile] = {}
    for name, data in worlds.items():
        if not isinstance(data, dict):
            raise ValueError(f"{catalog}: {name} must be a mapping")
        def number(key: str, default: float) -> float:
            value = data.get(key)
            return default if value is None else float(value)

        out[_key(name)] = WorldProfile(
            world_name=_key(name),
            map=str(data.get("map") or ""),
            inflation_radius=number("inflation_radius", 0.0),
            spawn_x=number("spawn_x", 0.0),
            spawn_y=number("spawn_y", 0.0),
            spawn_spacing=number("spawn_spacing", 1.5),
            world_source=str(data.get("world_source") or ""),
        )
    return out


def spawn_xy(index: int, spawn_x: float, spawn_y: float, spacing: float) -> tuple[float, float]:
    """1-based robot index. x grows by spacing. Same numbers seed AMCL (D-115)."""
    if index < 1:
        raise ValueError(f"robot index must be >= 1, got {index}")
    return spawn_x + (index - 1) * spacing, spawn_y


def parse_spawn_poses(text: str, robots: int) -> list[tuple[float, float, float]]:
    """`x,y,yaw_rad;x,y,yaw_rad;...`, one per robot in namespace order. Empty: []."""
    text = (text or "").strip()
    if not text:
        return []
    poses = []
    for item in text.split(";"):
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 3:
            raise ValueError(f"spawn pose {item!r} is not x,y,yaw_rad")
        poses.append(tuple(float(p) for p in parts))
    if len(poses) != robots:
        raise ValueError(f"spawn_poses has {len(poses)} poses for {robots} robots")
    return poses


def profile_for(world_name: str, path: Path | None = None) -> WorldProfile:
    worlds = load_worlds(path)
    key = _key(world_name)
    if key in worlds:
        return worlds[key]
    return WorldProfile(world_name=key)


def resolve_world(
    world_name: str,
    *,
    inflation_radius: Optional[float] = None,
    spawn_x: Optional[float] = None,
    spawn_y: Optional[float] = None,
    spawn_spacing: Optional[float] = None,
    map_yaml: Optional[str] = None,
    path: Path | None = None,
) -> WorldProfile:
    base = profile_for(world_name, path)
    updates = {}
    if inflation_radius is not None:
        updates["inflation_radius"] = inflation_radius
    if spawn_x is not None:
        updates["spawn_x"] = spawn_x
    if spawn_y is not None:
        updates["spawn_y"] = spawn_y
    if spawn_spacing is not None:
        updates["spawn_spacing"] = spawn_spacing
    if map_yaml:
        updates["map"] = map_yaml
    return base.overlay(**updates) if updates else base


def _package_uri_path(uri: str, package_share) -> Path:
    prefix = "package://"
    if not uri.startswith(prefix):
        raise ValueError(f"not a package URI: {uri}")
    package, separator, relative = uri[len(prefix):].partition("/")
    if not package or not separator or not relative:
        raise ValueError(f"invalid package URI: {uri}")
    return Path(package_share(package)) / relative


def resolve_world_path(
    profile: WorldProfile,
    gz_sim_share: Path,
    *,
    package_share,
) -> Path:
    """Resolve a catalog world without copying another package's source asset."""
    if profile.world_source:
        return _package_uri_path(profile.world_source, package_share)
    return Path(gz_sim_share) / "worlds" / profile.world_name


def world_share_parent(profile: WorldProfile, package_share) -> str:
    """`:<share parent>` of the package a catalog world comes from, else "".

    Such a world (map_v2_fleet: package://control/...) loads model://<pkg>/ meshes;
    description/.. covers every package only in a merge-install layout, not in
    colcon's isolated default, so GZ_SIM_RESOURCE_PATH needs this entry too."""
    if not profile.world_source.startswith("package://"):
        return ""
    package = profile.world_source[len("package://"):].split("/", 1)[0]
    return ":" + str(Path(package_share(package)).parent)


def resolve_asset_path(value: str, default_root: Path, *, package_share) -> Path:
    if value.startswith("package://"):
        return _package_uri_path(value, package_share)
    return Path(default_root) / value
