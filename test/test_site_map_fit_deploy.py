"""D-375 map-fit overlay deploy wiring: the track files ride in the images, read-only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy/site"
MAP = "src/runtime/sensing/map/map_v2_fleet"


def _service(compose: str, name: str, following: str) -> str:
    return compose.split(f"  {name}:\n", 1)[1].split(f"  {following}:\n", 1)[0]


def test_vision_runs_with_the_baked_lane_paint():
    compose = (SITE / "compose.yaml").read_text(encoding="utf-8")
    vision = _service(compose, "vision", "proxy")
    assert "--map-paint\n      - /opt/rosy/maps/map_v2_fleet/road_lines.stl" in vision
    dockerfile = (SITE / "Dockerfile.vision").read_text(encoding="utf-8")
    assert f"COPY {MAP}/meshes/road_lines.stl /opt/rosy/maps/map_v2_fleet/road_lines.stl" in dockerfile
    assert f"!{MAP}/meshes/road_lines.stl" in (SITE / "Dockerfile.vision.dockerignore").read_text(encoding="utf-8")


def test_fleet_serves_the_baked_lane_graph_and_paint():
    compose = (SITE / "compose.yaml").read_text(encoding="utf-8")
    fleet = _service(compose, "fleet", "vision")
    assert "--site-lane-graph\n      - /opt/rosy/maps/map_v2_fleet/lane_graph.yaml" in fleet
    assert "--site-lane-paint\n      - /opt/rosy/maps/map_v2_fleet/road_lines.stl" in fleet
    dockerfile = (SITE / "Dockerfile.fleet").read_text(encoding="utf-8")
    assert f"{MAP}/lane_graph.yaml {MAP}/meshes/road_lines.stl /opt/rosy/maps/map_v2_fleet/" in dockerfile
    ignore = (SITE / "Dockerfile.fleet.dockerignore").read_text(encoding="utf-8")
    assert f"!{MAP}/lane_graph.yaml" in ignore and f"!{MAP}/meshes/road_lines.stl" in ignore
    for rel in ("lane_graph.yaml", "meshes/road_lines.stl"):
        assert (ROOT / MAP / rel).is_file()


def test_both_services_stay_read_only():
    compose = (SITE / "compose.yaml").read_text(encoding="utf-8")
    for name, following in (("fleet", "vision"), ("vision", "proxy")):
        assert "read_only: true" in _service(compose, name, following)
