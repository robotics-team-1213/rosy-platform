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


def _ignored(patterns: list[str], path: str) -> bool:
    """BuildKit .dockerignore semantics: last matching pattern wins, and a pattern that
    matches a parent directory matches everything under it (so a bare `!src` re-includes
    the whole tree — the reason these files list leaf globs only)."""
    import re

    parts = path.split("/")
    candidates = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    ignored = False
    for raw in patterns:
        negate = raw.startswith("!")
        glob = raw[1:] if negate else raw
        regex = re.escape(glob).replace(r"\*\*/", "(.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        if any(re.fullmatch(regex, c) for c in candidates):
            ignored = not negate
    return ignored


def _copy_sources(dockerfile: str) -> list[str]:
    sources = []
    for line in dockerfile.splitlines():
        if line.startswith("COPY "):
            sources += [s.rstrip("/") for s in line.split()[1:-1]]
    return sources


def test_build_contexts_carry_only_what_the_images_copy():
    for name in ("vision", "fleet"):
        patterns = [line.strip() for line in
                    (SITE / f"Dockerfile.{name}.dockerignore").read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")]
        assert not [p for p in patterns if p in ("!src", "!src/site", "!deploy", "!src/runtime")], name
        for source in _copy_sources((SITE / f"Dockerfile.{name}").read_text(encoding="utf-8")):
            probe = source if (ROOT / source).is_file() else f"{source}/__init__.py"
            assert not _ignored(patterns, probe), f"{name}: COPY source {source} is ignored"
        for outside in ("src/runtime/gateway/setup.py", f"{MAP}/lane_rules.yaml", "deploy/robot/README.md",
                        "private/x.jpg", "src/site/fleet/fleet/__pycache__/a.pyc"):
            assert _ignored(patterns, outside), f"{name}: {outside} leaks into the build context"
    assert _ignored(["**", "!src/site/fleet/**"], "src/other/x.py")
    assert not _ignored(["**", "!src"], "src/other/x.py")  # why bare dirs are banned


def test_both_services_stay_read_only():
    compose = (SITE / "compose.yaml").read_text(encoding="utf-8")
    for name, following in (("fleet", "vision"), ("vision", "proxy")):
        assert "read_only: true" in _service(compose, name, following)
