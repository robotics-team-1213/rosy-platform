import yaml
import pytest

from fleet.server.sightings_config import load_sighting_sources


def _write(path, rows):
    path.write_text(yaml.safe_dump({"sources": rows}), encoding="utf-8")
    return path


def _row(**changes):
    row = {
        "source_id": "ceiling_north", "token_env": "ROSY_FLEET_SIGHTING_TOKEN",
        "robot_ids": ["rosy_01"], "map_id": "site-v1",
        "calibration_revision": "cal-v3", "corner_marker_ids": [30, 31, 32, 33],
    }
    row.update(changes)
    return row


def test_loader_resolves_token_from_environment_without_storing_it_in_config(tmp_path):
    config = _write(tmp_path / "sightings.yaml", [_row()])

    sources = load_sighting_sources(config, environ={"ROSY_FLEET_SIGHTING_TOKEN": "runtime-secret"})

    assert len(sources) == 1
    assert sources[0].token == "runtime-secret"
    assert sources[0].source_id == "ceiling_north"
    assert "runtime-secret" not in config.read_text(encoding="utf-8")


def test_loader_fails_closed_on_missing_secret_and_unknown_fields(tmp_path):
    config = _write(tmp_path / "sightings.yaml", [_row()])
    with pytest.raises(ValueError, match="environment variable"):
        load_sighting_sources(config, environ={})

    config = _write(tmp_path / "sightings.yaml", [_row(token="do-not-allow")])
    with pytest.raises(ValueError, match="unknown fields"):
        load_sighting_sources(config, environ={"ROSY_FLEET_SIGHTING_TOKEN": "runtime-secret"})


ENV = {"ROSY_FLEET_SIGHTING_TOKEN": "runtime-secret"}


def test_source_credential_kind_defaults_to_static(tmp_path):
    config = _write(tmp_path / "sightings.yaml", [_row(phone_token_env="ROSY_PHONE_TOKEN")])
    assert load_sighting_sources(config, environ=ENV)[0].credential == "static"


def test_paired_source_needs_no_phone_token(tmp_path):
    config = _write(tmp_path / "sightings.yaml", [_row(credential="paired")])
    assert load_sighting_sources(config, environ=ENV)[0].credential == "paired"


@pytest.mark.parametrize("row, message", [
    (_row(credential="paired", phone_token_env="ROSY_PHONE_TOKEN"), "paired"),
    (_row(credential="static"), "phone_token_env"),
    (_row(credential="dynamic"), "static or paired"),
])
def test_credential_kind_rules_refuse_start(tmp_path, row, message):
    """D-341 6: static needs phone_token_env, paired forbids it."""
    config = _write(tmp_path / "sightings.yaml", [row])
    with pytest.raises(ValueError, match=message):
        load_sighting_sources(config, environ=ENV)
