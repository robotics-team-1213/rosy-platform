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


@pytest.mark.parametrize("bad, message", [
    ([34, 34], "distinct"), ([50], "0-49"), (["34"], "0-49"), ([True], "0-49"),
    ([30], "corner_marker_ids"), ([7], "robot_markers"),
])
def test_place_markers_are_distinct_ids_apart_from_corners_and_robots(tmp_path, bad, message):
    """D-564: place_markers is a validated id list; absent means none."""
    config = _write(tmp_path / "s.yaml", [_row(place_markers=[34, 35, 36, 37, 38])])
    assert load_sighting_sources(config, environ=ENV)[0].place_markers == (34, 35, 36, 37, 38)
    assert load_sighting_sources(_write(tmp_path / "s.yaml", [_row()]), environ=ENV)[0].place_markers == ()
    config = _write(tmp_path / "s.yaml", [_row(robot_markers={"rosy_01": 7}, place_markers=bad)])
    with pytest.raises(ValueError, match=message):
        load_sighting_sources(config, environ=ENV)


@pytest.mark.parametrize("bad, message", [
    ({"rosy_02": 90}, "not a robot of this source"), ({"rosy_01": "90"}, "finite degrees"),
    ({"rosy_01": True}, "finite degrees"), ({"rosy_01": 400}, "finite degrees"),
    ({"rosy_01": float("nan")}, "finite degrees"), ([90], "map robot ids"),
])
def test_marker_yaw_offsets_name_marker_robots_with_finite_degrees(tmp_path, bad, message):
    """D-587 4: a per-robot sticker yaw offset is accepted; a bad one refuses start."""
    good = _write(tmp_path / "s.yaml", [_row(robot_markers={"rosy_01": 40},
                                             marker_yaw_offset_deg={"rosy_01": 180})])
    assert load_sighting_sources(good, environ=ENV)[0].source_id == "ceiling_north"
    enrolled = _write(tmp_path / "s.yaml", [_row(robot_ids="enrolled", robot_markers={},
                                                 marker_yaw_offset_deg={"rosy_41": 180})])
    assert load_sighting_sources(enrolled, environ=ENV)[0].follow_roster  # D-580: any roster robot
    config = _write(tmp_path / "s.yaml", [_row(robot_markers={"rosy_01": 40},
                                               marker_yaw_offset_deg=bad)])
    with pytest.raises(ValueError, match=message):
        load_sighting_sources(config, environ=ENV)


def test_enrolled_source_follows_the_roster_with_robot_number_markers(tmp_path):
    """D-580: `robot_ids: enrolled` -> live roster targets, marker = robot number unless overridden."""
    from types import SimpleNamespace
    from fleet.server.roster import SiteRoster
    from fleet.server.sightings import SightingService
    from fleet.server.tracking import TrackingService
    from fleet.server.tracking_calibration import TrackingCalibrationStore

    config = _write(tmp_path / "sightings.yaml", [_row(robot_ids="enrolled", robot_markers={"rosy_41": 45})])
    source, = load_sighting_sources(config, environ=ENV)
    assert source.follow_roster and source.robot_ids == () and source.marker_overrides == (("rosy_41", 45),)
    sightings = SightingService([source], known_robot_ids=[])
    tracking = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore())
    console = SimpleNamespace(robot_ids=["rosy_40", "rosy_41", "rosy_45", "rosy_31", "robot-x"])
    roster = SiteRoster(console, sightings=sightings, tracking=tracking)
    roster.sync()
    current, = sightings.sources
    assert current.robot_ids == ("robot-x", "rosy_31", "rosy_40", "rosy_41", "rosy_45")
    # rosy_45's number is the override of rosy_41; rosy_31 is outside 40-49; robot-x has no number.
    assert dict(current.robot_markers) == {"rosy_40": 40, "rosy_41": 45}
    assert tracking.sources == sightings.sources
    assert tracking.config_for("Bearer runtime-secret")["robot_markers"] == {"rosy_40": 40, "rosy_41": 45}
    console.robot_ids = ["rosy_41"]  # rosy_40 unenrolled: its target and marker go with it
    roster.sync()
    assert sightings.sources[0].robot_ids == ("rosy_41",) and dict(sightings.sources[0].robot_markers) == {"rosy_41": 45}
    assert sightings.known_robot_ids == {"rosy_41"}


def test_fixed_robot_ids_still_refuse_markers_outside_them(tmp_path):
    config = _write(tmp_path / "sightings.yaml", [_row(robot_markers={"rosy_02": 40})])
    with pytest.raises(ValueError, match="outside robot_ids"):
        load_sighting_sources(config, environ=ENV)
    config = _write(tmp_path / "sightings.yaml", [_row(robot_ids="all")])
    with pytest.raises(ValueError, match="enrolled"):
        load_sighting_sources(config, environ=ENV)
