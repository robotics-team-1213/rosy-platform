import numpy as np
import pytest

from control.sensing.perception.camera_ground import simulation_ground_plane

from control.sensing.perception.road import (
    PreviewRateLimiter,
    RoadObservation,
    RoadPreviewConfig,
    RoadPerceptionConfig,
    detect_road_observation,
    render_road_preview,
    road_observation_payload,
)


WIDTH = 320
HEIGHT = 240


def _longitudinal_crosswalk_frame(centres=(-.06, -.02, .02, .06), *, extent=(.22, .34)):
    # Project the source map's four 25 mm x 120 mm bars at 40 mm pitch through the nominal camera.
    ground = simulation_ground_plane(
        source='GAZEBO', simulation_enabled=True, use_sim_time=True,
        width_px=WIDTH, height_px=HEIGHT, height_m=.06343,
        pitch_rad=.13962634015954636, hfov_rad=1.0334, max_range_m=.6)
    frame = np.full((HEIGHT, WIDTH, 3), 35, dtype=np.uint8)
    for row in range(HEIGHT):
        distance = ground.distance(row)
        if distance is not None and extent[0] <= distance <= extent[1]:
            for column in range(WIDTH):
                lateral = ground.lateral(column, row)
                if any(abs(lateral-centre) <= .0125 for centre in centres):
                    frame[row, column] = 245
    return frame, ground


def test_260919_longitudinal_crosswalk_has_metric_road_evidence():
    frame, ground = _longitudinal_crosswalk_frame()
    observation = detect_road_observation(frame, ground=ground)
    assert observation.crosswalk is not None
    assert observation.stop_line is None
    assert observation.crosswalk.distance_m == pytest.approx(.22, abs=.01)
    assert 0 < observation.crosswalk.confidence <= 1
    assert ground.distance(observation.crosswalk.image_row) == pytest.approx(observation.crosswalk.distance_m)
    assert detect_road_observation(frame).crosswalk is None
    assert detect_road_observation(frame, ground=ground,
                                  config=RoadPerceptionConfig(crosswalk_min_bars=5)).crosswalk is None


@pytest.mark.parametrize("centres", [(), (-.02, .02), (.125, .165, .205, .245)])
def test_metric_crosswalk_requires_three_bars_in_this_corridor(centres):
    frame, ground = _longitudinal_crosswalk_frame(centres)
    if centres:
        assert (frame > 180).any()
    assert detect_road_observation(frame, ground=ground).crosswalk is None


def test_unprojected_disjoint_mark_remains_a_conservative_stop_candidate():
    frame = np.full((HEIGHT, WIDTH, 3), 35, dtype=np.uint8)
    for start in (0, 58, 105, 153, 200, 298):
        frame[135:139, start:start + 22] = 245
    assert (frame[136, :, 0] > 180).mean() > .4
    assert detect_road_observation(frame).stop_line is not None


@pytest.mark.parametrize('stop_row', [130, 160, 190])
def test_independent_stop_bar_is_retained_with_longitudinal_crosswalk(stop_row):
    frame, ground = _longitudinal_crosswalk_frame()
    frame[stop_row - 2:stop_row + 2, 55:265] = 245
    observation = detect_road_observation(frame, ground=ground)
    assert observation.crosswalk is not None
    assert observation.stop_line is not None
    assert observation.stop_line.image_row == pytest.approx(stop_row, abs=3)


@pytest.mark.parametrize('gap', [1, 2, 10])
def test_broken_stop_bar_is_retained_with_longitudinal_crosswalk(gap):
    frame, ground = _longitudinal_crosswalk_frame()
    frame[158:162, 55:265] = 245
    frame[158:162, 159:159 + gap] = 35
    observation = detect_road_observation(frame, ground=ground)
    assert observation.crosswalk is not None
    assert observation.stop_line is not None
    assert observation.stop_line.image_row == pytest.approx(160, abs=3)


def test_stop_bar_at_edge_of_merged_stripe_group_is_retained():
    frame, ground = _longitudinal_crosswalk_frame()
    frame[90:, :24] = 245
    frame[90:, -24:] = 245
    frame[159:161, 55:265] = 245
    observation = detect_road_observation(frame, ground=ground)
    assert observation.crosswalk is not None
    assert observation.stop_line is not None


@pytest.mark.parametrize('stop_row', [172, 185, 190])
def test_thin_stop_bar_survives_bev_source_row_aliasing(stop_row):
    frame, ground = _longitudinal_crosswalk_frame(extent=(.12, .25))
    frame[90:, :24] = 245
    frame[90:, -24:] = 245
    frame[stop_row, 55:265] = 245
    observation = detect_road_observation(frame, ground=ground)
    assert observation.crosswalk is not None
    assert observation.stop_line is not None


@pytest.mark.parametrize("marking", [{"lane_x": 160}, {"stop_y": 180}])
def test_metric_crosswalk_does_not_reclassify_a_lane_or_single_stop_line(marking):
    ground = simulation_ground_plane(
        source='GAZEBO', simulation_enabled=True, use_sim_time=True,
        width_px=WIDTH, height_px=HEIGHT, height_m=.06343,
        pitch_rad=.13962634015954636, hfov_rad=1.0334, max_range_m=.6)
    observation = detect_road_observation(_frame(**marking), ground=ground)
    assert observation.crosswalk is None
    assert (observation.stop_line is not None) == ('stop_y' in marking)


def _frame(*, lane_x=None, stop_y=None, crosswalk_rows=(), signals=()):
    frame = np.full((HEIGHT, WIDTH, 3), 35, dtype=np.uint8)
    if lane_x is not None:
        frame[70:, lane_x - 4:lane_x + 4] = (235, 235, 235)
    if stop_y is not None:
        frame[stop_y - 3:stop_y + 3, 55:265] = (245, 245, 245)
    for row in crosswalk_rows:
        frame[row - 2:row + 2, 75:245] = (245, 245, 245)
    colours = {
        "RED": (0, 0, 255),
        "YELLOW": (0, 255, 255),
        "GREEN": (0, 255, 0),
    }
    for index, colour in enumerate(signals):
        x0 = 20 + index * 28
        frame[20:38, x0:x0 + 18] = colours[colour]
    return frame


def test_lane_centroid_ignores_horizontal_stop_and_crosswalk_markings():
    observation = detect_road_observation(
        _frame(lane_x=220, stop_y=190, crosswalk_rows=(120, 132, 144, 156)))

    assert isinstance(observation, RoadObservation)
    assert observation.lane is not None
    assert observation.lane.error == pytest.approx((220 - 160) / 160, abs=0.04)
    assert observation.stop_line is not None
    assert observation.crosswalk is not None


def test_single_wide_horizontal_group_is_a_stop_line_not_a_crosswalk():
    observation = detect_road_observation(_frame(lane_x=160, stop_y=180))

    assert observation.stop_line is not None
    assert observation.stop_line.image_row == pytest.approx(180, abs=3)
    assert observation.crosswalk is None


def test_thick_stop_distance_uses_the_nearest_visible_edge():
    _, ground = _longitudinal_crosswalk_frame()
    frame = _frame(lane_x=220)
    frame[140:230, 55:265] = 245
    observation = detect_road_observation(frame, ground=ground)
    assert observation.stop_line.image_row == 229.0
    assert observation.stop_line.distance_m == pytest.approx(ground.distance(229))
    assert observation.stop_line.distance_m < .12 < ground.distance(184.5)
    payload = road_observation_payload('CAMERA_ROAD', 1., 'map', 'rev', observation)
    assert payload['stop_line']['image_row'] == 229.0
    assert payload['stop_line']['distance_m'] == observation.stop_line.distance_m
    assert observation.lane.error == pytest.approx(detect_road_observation(frame).lane.error)


def test_transverse_crosswalk_distance_matches_nearest_bar_edge():
    _, ground = _longitudinal_crosswalk_frame()
    frame = _frame(crosswalk_rows=(130, 145, 160))
    observation = detect_road_observation(frame, ground=ground)
    assert observation.stop_line is None
    assert observation.crosswalk.image_row == 161.0
    assert observation.crosswalk.distance_m == pytest.approx(ground.distance(161))


def test_same_colour_wall_and_attached_stop_remain_visible():
    _, ground = _longitudinal_crosswalk_frame()
    frame = _frame()
    frame[:123] = 240
    frame[123:131, 55:265] = 240
    observation = detect_road_observation(frame, ground=ground)
    assert observation.stop_line is not None
    assert observation.stop_line.image_row == 130.0
    assert observation.stop_line.distance_m == pytest.approx(ground.distance(130))
    assert observation.stop_line.confidence > .9


@pytest.mark.parametrize('case', ['thin_horizon', 'far_floor', 'above_horizon', 'no_ground', 'invalid_ground'])
def test_unknown_marking_range_preserves_visible_evidence(case):
    _, ground = _longitudinal_crosswalk_frame()
    frame = _frame()
    top, bottom = {'thin_horizon': (78, 84), 'far_floor': (81, 84),
                   'above_horizon': (30, 36)}.get(case, (170, 180))
    frame[top:bottom, 55:265] = 245
    if case == 'no_ground':
        ground = None
    elif case == 'invalid_ground':
        ground = simulation_ground_plane(source='GAZEBO', simulation_enabled=True, use_sim_time=True,
            width_px=WIDTH, height_px=HEIGHT, height_m=0., pitch_rad=.14, hfov_rad=1., max_range_m=.6)
        assert ground is None
    observation = detect_road_observation(frame, ground=ground)
    assert observation.stop_line is not None and observation.stop_line.distance_m is None
    assert observation.stop_line.image_row == float(bottom - 1)
    assert observation.stop_line.confidence > .5


def test_repeated_wide_horizontal_groups_are_a_crosswalk():
    observation = detect_road_observation(
        _frame(lane_x=160, crosswalk_rows=(125, 137, 149, 161)))

    assert observation.crosswalk is not None
    assert observation.crosswalk.image_row == pytest.approx(161, abs=4)
    assert observation.stop_line is None


@pytest.mark.parametrize("colour", ["RED", "YELLOW", "GREEN"])
def test_upper_image_traffic_signal_colour_is_recognized(colour):
    observation = detect_road_observation(
        _frame(lane_x=160, signals=(colour,)))

    assert observation.signal is not None
    assert observation.signal.colour == colour
    assert observation.signal.confidence > 0.5
    assert observation.signal_conflict is False


def test_multiple_signal_colours_fail_as_conflicting_evidence():
    observation = detect_road_observation(
        _frame(lane_x=160, signals=("RED", "GREEN")))

    assert observation.signal is None
    assert observation.signal_conflict is True


def test_blank_frame_reports_no_features_without_inventing_distance():
    observation = detect_road_observation(_frame())

    assert observation.lane is None
    assert observation.stop_line is None
    assert observation.crosswalk is None
    assert observation.signal is None
    assert observation.signal_conflict is False


def test_validated_ground_model_supplies_metric_feature_distance():
    class Ground:
        def distance(self, row, column=None):
            assert column == pytest.approx(WIDTH / 2)
            return row / 1000.0

    observation = detect_road_observation(
        _frame(lane_x=160, stop_y=180), ground=Ground())

    assert observation.stop_line is not None
    assert observation.stop_line.distance_m == pytest.approx(0.18, abs=0.01)


def test_payload_is_strict_json_shape_and_observations_are_immutable():
    observation = detect_road_observation(
        _frame(lane_x=160, stop_y=180, signals=("RED",)))

    payload = road_observation_payload(
        "CAMERA_ROAD", 12.5, "map_260905_update_v2",
        "road-scene-v1", observation)

    assert payload == {
        "source": "CAMERA_ROAD",
        "stamp": 12.5,
        "map_id": "map_260905_update_v2",
        "scene_revision": "road-scene-v1",
        "lane": {
            "visible": True,
            "error": pytest.approx(0.0, abs=0.02),
            "confidence": pytest.approx(observation.lane.confidence),
        },
        "stop_line": {
            "visible": True,
            "image_row": pytest.approx(180, abs=3),
            "distance_m": None,
            "confidence": pytest.approx(observation.stop_line.confidence),
        },
        "crosswalk": {
            "visible": False,
            "image_row": None,
            "distance_m": None,
            "confidence": 0.0,
        },
        "signal": {
            "visible": True,
            "colour": "RED",
            "confidence": pytest.approx(observation.signal.confidence),
            "conflict": False,
        },
    }
    with pytest.raises((AttributeError, TypeError)):
        observation.signal_conflict = True


@pytest.mark.parametrize(
    "args",
    [
        ("IR_LINE", 1.0, "map", "scene"),
        ("CAMERA_ROAD", float("nan"), "map", "scene"),
        ("CAMERA_ROAD", 1.0, "", "scene"),
        ("CAMERA_ROAD", 1.0, "map", ""),
    ],
)
def test_payload_rejects_unbound_or_invalid_evidence(args):
    with pytest.raises(ValueError):
        road_observation_payload(*args, detect_road_observation(_frame()))


def test_payload_omits_scene_context_by_default():
    payload = road_observation_payload(
        "CAMERA_ROAD", 1.0, "map", "rev",
        RoadObservation(None, None, None, None, False))

    assert "context" not in payload


def test_payload_carries_scene_context_when_provided():
    payload = road_observation_payload(
        "CAMERA_ROAD", 1.0, "map", "rev",
        RoadObservation(None, None, None, None, False),
        context_id="crosswalk",
        context_confidence=0.8,
        context_profile_revision="ctx-crosswalk-v1")

    assert payload["context"] == {
        "id": "crosswalk",
        "confidence": 0.8,
        "profile_revision": "ctx-crosswalk-v1",
    }


@pytest.mark.parametrize("drop", ["context_id", "context_confidence",
                                  "context_profile_revision"])
def test_payload_rejects_partial_scene_context(drop):
    kwargs = {
        "context_id": "crosswalk",
        "context_confidence": 0.8,
        "context_profile_revision": "ctx-crosswalk-v1",
    }
    kwargs.pop(drop)

    with pytest.raises(ValueError):
        road_observation_payload(
            "CAMERA_ROAD", 1.0, "map", "rev",
            RoadObservation(None, None, None, None, False), **kwargs)


@pytest.mark.parametrize("confidence", [-0.1, 1.5, float("nan"), True])
def test_payload_rejects_out_of_range_context_confidence(confidence):
    with pytest.raises(ValueError):
        road_observation_payload(
            "CAMERA_ROAD", 1.0, "map", "rev",
            RoadObservation(None, None, None, None, False),
            context_id="crosswalk",
            context_confidence=confidence,
            context_profile_revision="ctx-crosswalk-v1")


def test_preview_draws_detected_evidence_without_mutating_source_frame():
    source = _frame(
        lane_x=220, stop_y=190,
        crosswalk_rows=(120, 132, 144, 156), signals=("RED",))
    original = source.copy()
    observation = detect_road_observation(source)

    preview = render_road_preview(
        source, observation, source="GAZEBO", max_width=240)

    assert np.array_equal(source, original)
    assert preview.shape == (180, 240, 3)
    assert not np.array_equal(
        preview, source[::source.shape[0] // preview.shape[0],
                        ::source.shape[1] // preview.shape[1]][
                            :preview.shape[0], :preview.shape[1]])
    # The overlay carries a strong cyan guide that is absent from the fixture.
    assert np.any(np.all(preview == (255, 220, 0), axis=2))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fps": 2.01},
        {"fps": 0.19},
        {"max_width": 641},
        {"max_width": 159},
        {"jpeg_quality": 91},
        {"max_bytes": 512_001},
    ],
)
def test_preview_config_rejects_values_outside_transport_budget(kwargs):
    with pytest.raises(ValueError):
        RoadPreviewConfig(**kwargs)


def test_preview_rate_limiter_uses_local_monotonic_time_and_resets_safely():
    limiter = PreviewRateLimiter(fps=2.0)

    assert limiter.allow(10.0) is True
    assert limiter.allow(10.1) is False
    assert limiter.allow(10.5) is True
    # Local monotonic regression starts a new epoch instead of wedging output.
    assert limiter.allow(0.0) is True


def test_preview_renderer_never_accepts_width_above_dashboard_budget():
    observation = detect_road_observation(_frame(lane_x=160))

    with pytest.raises(ValueError, match="640"):
        render_road_preview(
            _frame(lane_x=160), observation,
            source="GAZEBO", max_width=641,
        )
