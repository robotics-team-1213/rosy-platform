import yaml
import pytest

from overhead.vision_config import load_vision_sources


def _source(**changes):
    source = {
        "source_id": "ceiling_north",
        "phone_token_env": "ROSY_PHONE_CEILING_NORTH",
        "token_env": "ROSY_FLEET_CEILING_NORTH",
        "fleet_base_url": "https://fleet.example.test",
        "robot_ids": ["rosy_01"],
        "map_id": "site-v1",
        "calibration_revision": "cal-v3",
        "processor_revision": "aruco-v1",
        "corner_marker_ids": [30, 31, 32, 33],
        "corner_world_m": [[0, 0], [4, 0], [4, 2], [0, 2]],
        "robot_markers": {"rosy_01": 7},
        "heading_edge": [1, 2],
    }
    source.update(changes)
    return source


def _write(path, sources):
    path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    return path


def test_loader_builds_camera_maps_and_reads_distinct_runtime_secrets(tmp_path):
    path = _write(tmp_path / "site-cameras.yaml", [_source()])
    env = {
        "ROSY_PHONE_CEILING_NORTH": "phone-secret",
        "ROSY_FLEET_CEILING_NORTH": "vision-secret",
    }

    configs = load_vision_sources(path, environ=env)

    assert len(configs) == 1
    config = configs[0]
    assert config.camera.source_id == "ceiling_north"
    assert config.camera.robot_markers == {"rosy_01": 7}
    assert config.phone_token == "phone-secret"
    assert config.sighting_token == "vision-secret"
    assert config.phone_token != config.sighting_token
    assert "phone-secret" not in path.read_text(encoding="utf-8")


def test_loader_rejects_missing_or_reused_credentials(tmp_path):
    path = _write(tmp_path / "site-cameras.yaml", [_source()])
    with pytest.raises(ValueError, match="environment variable"):
        load_vision_sources(path, environ={})

    env = {"ROSY_PHONE_CEILING_NORTH": "shared",
           "ROSY_FLEET_CEILING_NORTH": "shared"}
    with pytest.raises(ValueError, match="distinct"):
        load_vision_sources(path, environ=env)
