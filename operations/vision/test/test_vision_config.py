import yaml
import pytest

from rosy_vision.vision_config import load_vision_sources


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


ENV = {"ROSY_PHONE_CEILING_NORTH": "phone-secret", "ROSY_FLEET_CEILING_NORTH": "vision-secret"}


@pytest.mark.parametrize("markers", [{}, {"rosy_01": 7}])
def test_marker_assignment_can_cover_only_some_tracking_targets(tmp_path, markers):
    row = _source(robot_ids=["rosy_01", "rosy_02"], robot_markers=markers)
    config = load_vision_sources(_write(tmp_path / "c.yaml", [row]), environ=ENV)[0]
    assert config.camera.robot_markers == markers


def test_marker_assignment_cannot_name_an_unknown_tracking_target(tmp_path):
    row = _source(robot_markers={"rosy_02": 7})
    with pytest.raises(ValueError, match="robot_markers"):
        load_vision_sources(_write(tmp_path / "c.yaml", [row]), environ=ENV)


def test_sources_default_to_static_with_a_phone_token(tmp_path):
    config = load_vision_sources(_write(tmp_path / "c.yaml", [_source()]), environ=ENV)[0]
    assert (config.credential, config.phone_token) == ("static", "phone-secret")


def test_paired_source_has_no_phone_token(tmp_path):
    row = _source(credential="paired")
    del row["phone_token_env"]
    config = load_vision_sources(_write(tmp_path / "c.yaml", [row]), environ=ENV)[0]
    assert (config.credential, config.phone_token) == ("paired", None)
    assert config.sighting_token == "vision-secret"


def test_static_without_phone_token_and_paired_with_one_refuse_start(tmp_path):
    """D-341 6: static requires phone_token_env, paired forbids it."""
    static = _source(credential="static")
    del static["phone_token_env"]
    with pytest.raises(ValueError, match="phone_token_env"):
        load_vision_sources(_write(tmp_path / "c.yaml", [static]), environ=ENV)
    with pytest.raises(ValueError, match="paired"):
        load_vision_sources(_write(tmp_path / "c.yaml", [_source(credential="paired")]), environ=ENV)
    with pytest.raises(ValueError, match="static or paired"):
        load_vision_sources(_write(tmp_path / "c.yaml", [_source(credential="qr")]), environ=ENV)


def test_field_boundary_source_drops_corner_markers(tmp_path):
    row = _source(calibration_source="field_boundary")
    del row["corner_marker_ids"]
    config = load_vision_sources(_write(tmp_path / "c.yaml", [row]), environ=ENV)[0]
    assert config.camera.calibration_source == "field_boundary"
    assert config.camera.corner_marker_ids is None


def test_field_boundary_refuses_corner_marker_ids_and_default_needs_them(tmp_path):
    both = _source(calibration_source="field_boundary")
    with pytest.raises(ValueError, match="must not set corner_marker_ids"):
        load_vision_sources(_write(tmp_path / "c.yaml", [both]), environ=ENV)
    missing = _source()
    del missing["corner_marker_ids"]
    with pytest.raises(ValueError, match="corner_marker_ids"):
        load_vision_sources(_write(tmp_path / "c.yaml", [missing]), environ=ENV)
    unknown = _source(calibration_source="paint_magic")
    with pytest.raises(ValueError, match="calibration_source"):
        load_vision_sources(_write(tmp_path / "c.yaml", [unknown]), environ=ENV)


@pytest.mark.parametrize("bad, message", [
    ([34, 34], "distinct"), ([50], "0-49"), ([30], "corner_marker_ids"), ([7], "robot_markers"),
])
def test_place_markers_are_distinct_ids_apart_from_corners_and_robots(tmp_path, bad, message):
    """D-564: same rule as the Fleet parser (one shared check)."""
    env = {"ROSY_PHONE_CEILING_NORTH": "phone-secret", "ROSY_FLEET_CEILING_NORTH": "vision-secret"}
    path = _write(tmp_path / "c.yaml", [_source(place_markers=[34, 35])])
    assert load_vision_sources(path, environ=env)[0].camera.place_markers == (34, 35)
    assert load_vision_sources(_write(tmp_path / "c.yaml", [_source()]), environ=env)[0].camera.place_markers == ()
    with pytest.raises(ValueError, match=message):
        load_vision_sources(_write(tmp_path / "c.yaml", [_source(place_markers=bad)]), environ=env)


def test_marker_yaw_offsets_reach_the_camera_map_and_bad_ones_refuse_start(tmp_path):
    """D-587 4: per-robot sticker yaw offset, shared check with Fleet."""
    path = _write(tmp_path / "s.yaml", [_source(marker_yaw_offset_deg={"rosy_01": -90})])
    camera = load_vision_sources(path, environ=ENV)[0].camera
    assert camera.marker_yaw_offset_deg == {"rosy_01": -90.0}
    assert load_vision_sources(_write(tmp_path / "s.yaml", [_source()]), environ=ENV)[0].camera.marker_yaw_offset_deg == {}
    # D-580 roster source: a robot on its default marker (no YAML override) may carry an offset.
    enrolled = _write(tmp_path / "s.yaml", [_source(robot_ids="enrolled", robot_markers={},
                                                    marker_yaw_offset_deg={"rosy_40": 180})])
    assert load_vision_sources(enrolled, environ=ENV)[0].camera.marker_yaw_offset_deg == {"rosy_40": 180.0}
    for bad in ({"rosy_02": 0}, {"rosy_01": "180"}, {"rosy_01": 361}, {"bad id": 0}):
        with pytest.raises(ValueError, match="marker_yaw_offset_deg"):
            load_vision_sources(_write(tmp_path / "s.yaml", [_source(marker_yaw_offset_deg=bad)]),
                                environ=ENV)


def test_enrolled_robot_ids_take_markers_from_fleet_and_fall_back_to_yaml(tmp_path):
    """D-580: Fleet's tracking config names the roster markers; the YAML is the fallback."""
    from types import SimpleNamespace
    from rosy_vision.worker import VisionWorker

    path = _write(tmp_path / "site-cameras.yaml", [_source(robot_ids="enrolled", robot_markers={"rosy_41": 45})])
    camera = load_vision_sources(path, environ={"ROSY_PHONE_CEILING_NORTH": "p",
                                                "ROSY_FLEET_CEILING_NORTH": "f"})[0].camera
    tracker = SimpleNamespace(config=None)
    worker = VisionWorker(source_id="ceiling_north", ingest=None, camera=camera, publisher=None, tracker=tracker)
    assert worker._camera().robot_markers == {"rosy_41": 45}  # Fleet not read yet
    tracker.config = {"robot_markers": {"rosy_40": 40, "rosy_41": 45}}
    assert worker._camera().robot_markers == {"rosy_40": 40, "rosy_41": 45}
    assert worker._camera().heading_edge == camera.heading_edge  # sticker front stays the YAML's (D-562)
    tracker.config = {"robot_markers": {"rosy_40": 30}}  # would hide a corner: refused, YAML kept
    assert worker._camera().robot_markers == {"rosy_41": 45}


_ENV = {"ROSY_PHONE_CEILING_NORTH": "phone-secret", "ROSY_FLEET_CEILING_NORTH": "vision-secret"}


def test_auto_tune_defaults_on_and_can_be_turned_off(tmp_path):
    """D-589 6: Vision tunes the camera unless the source says auto_tune: false."""
    assert load_vision_sources(_write(tmp_path / "a.yaml", [_source()]), environ=_ENV)[0].auto_tune is True
    off = load_vision_sources(_write(tmp_path / "b.yaml", [_source(auto_tune=False)]), environ=_ENV)
    assert off[0].auto_tune is False


@pytest.mark.parametrize("value", ["false", 0, 1, None, "yes"])
def test_auto_tune_must_be_a_boolean(tmp_path, value):
    with pytest.raises(ValueError, match="auto_tune"):
        load_vision_sources(_write(tmp_path / "c.yaml", [_source(auto_tune=value)]), environ=_ENV)
