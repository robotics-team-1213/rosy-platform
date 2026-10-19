"""Fleet's minimal configuration remains valid without Vision credentials."""

import pytest

from core_common.protocol.sighting_sources import validate_sighting_config


def source(**changes):
    return dict(source_id="camera", token_env="CAMERA_TOKEN", robot_ids=["robot"],
                map_id="map", calibration_revision="v1", corner_marker_ids=[1, 2, 3, 4], **changes)


def test_minimal_fleet_source_and_optional_identity():
    validate_sighting_config({"sources": [source()], "identity": {}})


@pytest.mark.parametrize("config", [None, {}, {"sources": []}, {"sources": [None]},
                                      {"sources": [{}]}, {"sources": [source(extra=True)]}])
def test_malformed_config_is_rejected(config):
    with pytest.raises(ValueError):
        validate_sighting_config(config)


def test_field_boundary_needs_world_corners():
    row = source(calibration_source="field_boundary")
    del row["corner_marker_ids"]
    with pytest.raises(ValueError, match="needs corner_world_m"):
        validate_sighting_config({"sources": [row]})
