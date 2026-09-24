"""월드 카탈로그 — 미로/공장 숫자는 YAML에만 있다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "launch" / "world_profiles.py"


def _mod():
    spec = importlib.util.spec_from_file_location("world_profiles", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_worlds():
    return _mod().load_worlds()


def profile_for(name):
    return _mod().profile_for(name)


def resolve_world(*args, **kwargs):
    return _mod().resolve_world(*args, **kwargs)


def test_catalog_names_every_shipped_world():
    worlds = load_worlds()
    on_disk = {path.name for path in (ROOT / "worlds").glob("*.world")}
    # empty/default sdf worlds are not nav benches
    benches = on_disk - {"empty.world"}
    missing = benches - set(worlds)
    assert not missing, f"catalog missing worlds: {missing}"


def test_factory_and_maze_do_not_share_inflation():
    factory = profile_for("rosy_factory.world")
    maze = profile_for("rosy_maze")
    assert factory.inflation_radius == 0.25
    assert maze.inflation_radius == 0.55
    assert factory.map == "rosy_factory.yaml"
    assert maze.map == "rosy_maze.yaml"
    assert (factory.spawn_x, factory.spawn_y) != (0.0, 0.0)
    assert (maze.spawn_x, maze.spawn_y) != (factory.spawn_x, factory.spawn_y)


def test_spawn_xy_spaces_robots_along_x_and_keeps_factory_off_the_origin():
    """D-115: 시드와 spawn 은 같은 숫자다. factory 두 대는 (0,0) 이 아니다."""
    factory = profile_for("rosy_factory.world")
    first = _mod().spawn_xy(1, factory.spawn_x, factory.spawn_y, factory.spawn_spacing)
    second = _mod().spawn_xy(2, factory.spawn_x, factory.spawn_y, factory.spawn_spacing)
    assert first == pytest.approx((-0.2, 1.05))
    assert second == pytest.approx((0.4, 1.05))
    assert first != (0.0, 0.0)
    assert second != first


def test_launch_args_override_the_catalog_not_the_other_way_around():
    maze = resolve_world("rosy_maze.world", inflation_radius=0.2, spawn_x=1.0)
    assert maze.inflation_radius == 0.2
    assert maze.spawn_x == 1.0
    assert maze.map == "rosy_maze.yaml"
    untouched = resolve_world("rosy_maze.world")
    assert untouched.inflation_radius == 0.55


def test_exact_v2_world_resolves_to_the_installed_control_bundle():
    mod = _mod()
    profile = profile_for("map_260905.world")

    assert profile.world_source == (
        "package://control/map/map_260905_update_v2/worlds/map_260905.world"
    )
    assert profile.map == "package://control/map/map_260905_update_v2/maps/map_260905.yaml"
    assert profile.spawn_x == pytest.approx(-0.205)
    assert profile.spawn_y == pytest.approx(0.275)
    assert profile.spawn_spacing == 0.0
    assert profile.inflation_radius > 0.0

    resolved = mod.resolve_world_path(
        profile,
        Path("/opt/ros/share/gz_sim"),
        package_share=lambda package: Path("/opt/ros/share") / package,
    )
    assert resolved == Path(
        "/opt/ros/share/control/map/map_260905_update_v2/worlds/map_260905.world"
    )


def test_control_package_installs_the_complete_v2_map_bundle():
    setup_py = (ROOT.parents[1] / "core" / "control" / "setup.py").read_text(
        encoding="utf-8"
    )
    assert "map_260905_update_v2" in setup_py
    assert "recursive=True" in setup_py


def test_map_v2_fleet_is_catalogued_from_the_control_bundle():
    profile = profile_for("map_v2_fleet.world")
    assert profile.world_source == (
        "package://control/map/map_v2_fleet/worlds/map_v2_fleet.world")
    assert profile.map == "package://control/map/map_v2_fleet/maps/map_v2_fleet.yaml"
    assert profile.spawn_x == pytest.approx(-1.26955)
    assert profile.spawn_y == pytest.approx(0.24255)
    assert profile.spawn_spacing == 0.0


def test_control_package_installs_the_map_v2_fleet_bundle():
    setup_py = (ROOT.parents[1] / "core" / "control" / "setup.py").read_text(
        encoding="utf-8")
    assert "map_v2_fleet" in setup_py
