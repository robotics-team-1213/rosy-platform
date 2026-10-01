"""deploy/site/site-cameras.yaml.example stays loadable by Vision and Fleet (D-341 credential kinds)."""

from pathlib import Path

from fleet.server.sightings_config import load_sighting_sources
from rosy_vision.vision_config import load_vision_sources

EXAMPLE = Path(__file__).resolve().parents[4] / "deploy/site/site-cameras.yaml.example"
ENV = {"ROSY_PHONE_CEILING_NORTH": "phone-north", "ROSY_FLEET_CEILING_NORTH_TOKEN": "fleet-north",
       "ROSY_FLEET_CEILING_SOUTH_TOKEN": "fleet-south"}


def test_example_loads_static_and_with_its_paired_block_enabled(tmp_path):
    head, marker, tail = EXAMPLE.read_text(encoding="utf-8").partition("  # A paired source")
    assert marker
    block = [line.replace("  # ", "  ", 1) for line in tail.splitlines()[1:]
             if line.startswith("  # ") and not line.startswith("  # Fleet issues")]
    static = tmp_path / "static.yaml"
    static.write_text(head, encoding="utf-8")
    both = tmp_path / "both.yaml"
    both.write_text(head + "\n".join(block) + "\n", encoding="utf-8")
    assert [c.credential for c in load_vision_sources(static, environ=ENV)] == ["static"]
    assert [c.credential for c in load_vision_sources(both, environ=ENV)] == ["static", "paired"]
    assert [c.credential for c in load_sighting_sources(both, environ=ENV)] == ["static", "paired"]
