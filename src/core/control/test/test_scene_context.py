import pytest

from control.sensing.road import (
    LaneObservation,
    RoadMarkingObservation,
    RoadObservation,
)
from control.sensing.scene_context import (
    GENERIC_CONTEXT_ID,
    GENERIC_PROFILE_REVISION,
    SceneContextMatcher,
    SceneContextProfile,
    SceneContextStore,
    default_scene_context_store,
    generic_scene_context_profile,
)


def _store(**options):
    profiles = [
        generic_scene_context_profile(),
        SceneContextProfile(
            context_id="lane_follow", profile_revision="ctx-lane-v1"),
        SceneContextProfile(
            context_id="stop_line", profile_revision="ctx-stop-v1"),
        SceneContextProfile(
            context_id="crosswalk", profile_revision="ctx-crosswalk-v1"),
    ]
    if options.pop("drop_generic", False):
        profiles = profiles[1:]
    profiles.extend(options.pop("extra", []))
    return SceneContextStore(profiles)


def _marking(confidence=0.9):
    return RoadMarkingObservation(
        image_row=100.0, distance_m=None, confidence=confidence)


def _observation(*, lane=None, stop_line=None, crosswalk=None, conflict=False):
    return RoadObservation(
        lane=lane,
        stop_line=stop_line,
        crosswalk=crosswalk,
        signal=None,
        signal_conflict=conflict,
    )


def _crosswalk_observation(confidence=0.9, conflict=False):
    return _observation(crosswalk=_marking(confidence), conflict=conflict)


# --- profile validation -----------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("bright_threshold", 0),
    ("bright_threshold", 255),
    ("bright_threshold", True),
    ("lane_roi_top_fraction", 0.0),
    ("horizontal_min_fraction", 1.5),
    ("signal_roi_bottom_fraction", -0.1),
    ("horizontal_padding_px", -1),
    ("crosswalk_max_gap_px", -2),
    ("crosswalk_min_bars", 0),
    ("signal_min_pixels", 0),
])
def test_profile_rejects_out_of_range_values(field, value):
    with pytest.raises(ValueError):
        SceneContextProfile(context_id="crosswalk",
                            profile_revision="ctx-x", **{field: value})


def test_profile_requires_identifiers():
    with pytest.raises(ValueError):
        SceneContextProfile(context_id="  ", profile_revision="ctx-x")
    with pytest.raises(ValueError):
        SceneContextProfile(context_id="crosswalk", profile_revision="")


def test_generic_profile_uses_canonical_revision():
    profile = generic_scene_context_profile()
    assert profile.context_id == GENERIC_CONTEXT_ID
    assert profile.profile_revision == GENERIC_PROFILE_REVISION


def test_default_store_registers_neutral_contexts():
    store = default_scene_context_store()
    assert store.generic.profile_revision == GENERIC_PROFILE_REVISION
    assert store.profile("lane_follow").profile_revision == "ctx-lane-v1"
    assert store.profile("stop_line").profile_revision == "ctx-stop-v1"
    assert store.profile("crosswalk").profile_revision == "ctx-crosswalk-v1"
    # Neutral by design: no scene-specific tuning before DEVICE evidence.
    generic = store.generic.perception_config()
    assert store.profile("lane_follow").perception_config() == generic
    assert store.profile("stop_line").perception_config() == generic
    assert store.profile("crosswalk").perception_config() == generic


def test_profile_perception_config_matches_fields():
    profile = SceneContextProfile(
        context_id="crosswalk",
        profile_revision="ctx-crosswalk-v1",
        bright_threshold=170,
        lane_roi_top_fraction=0.25,
        horizontal_min_fraction=0.35,
        horizontal_padding_px=3,
        crosswalk_min_bars=4,
        crosswalk_max_gap_px=24,
        signal_roi_bottom_fraction=0.40,
        signal_min_pixels=40,
    )
    config = profile.perception_config()
    assert config.bright_threshold == 170
    assert config.lane_roi_top_fraction == pytest.approx(0.25)
    assert config.horizontal_min_fraction == pytest.approx(0.35)
    assert config.horizontal_padding_px == 3
    assert config.crosswalk_min_bars == 4
    assert config.crosswalk_max_gap_px == 24
    assert config.signal_roi_bottom_fraction == pytest.approx(0.40)
    assert config.signal_min_pixels == 40


# --- store contract ---------------------------------------------------------


def test_store_requires_generic_profile():
    with pytest.raises(ValueError):
        _store(drop_generic=True)


def test_store_rejects_duplicate_context_id():
    with pytest.raises(ValueError):
        _store(extra=[SceneContextProfile(
            context_id="crosswalk", profile_revision="ctx-other-v1")])


def test_store_rejects_duplicate_revision():
    with pytest.raises(ValueError):
        _store(extra=[SceneContextProfile(
            context_id="stop_line", profile_revision="ctx-stop-v1")])


def test_store_rejects_unknown_context_id():
    with pytest.raises(ValueError):
        _store(extra=[SceneContextProfile(
            context_id="tunnel", profile_revision="ctx-tunnel-v1")])


def test_store_lookup_fails_closed_on_unknown_id():
    store = _store()
    with pytest.raises(KeyError):
        store.profile("tunnel")
    assert store.generic.profile_revision == GENERIC_PROFILE_REVISION


# --- matcher classification -------------------------------------------------


def test_matcher_starts_generic_and_ignores_weak_evidence():
    matcher = SceneContextMatcher(_store())
    weak = _observation(
        lane=LaneObservation(error=0.1, confidence=0.2))
    scene = matcher.update(weak)
    assert scene.context_id == GENERIC_CONTEXT_ID
    assert scene.confidence == 0.0


def test_matcher_switches_after_enter_frames_confirmations():
    matcher = SceneContextMatcher(_store(), enter_frames=3)
    assert matcher.update(_crosswalk_observation()).context_id \
        == GENERIC_CONTEXT_ID
    assert matcher.update(_crosswalk_observation()).context_id \
        == GENERIC_CONTEXT_ID
    scene = matcher.update(_crosswalk_observation())
    assert scene.context_id == "crosswalk"
    assert scene.profile_revision == "ctx-crosswalk-v1"
    assert scene.confidence == pytest.approx(0.9)


def test_crosswalk_outranks_stop_line_outranks_lane():
    matcher = SceneContextMatcher(_store(), enter_frames=2)
    crowded = _observation(
        lane=LaneObservation(error=0.0, confidence=0.9),
        stop_line=_marking(0.9),
        crosswalk=_marking(0.9),
    )
    matcher.update(crowded)
    assert matcher.update(crowded).context_id == "crosswalk"

    lane_and_stop = _observation(
        lane=LaneObservation(error=0.0, confidence=0.9),
        stop_line=_marking(0.9),
    )
    matcher.reset()
    matcher.update(lane_and_stop)
    assert matcher.update(lane_and_stop).context_id == "stop_line"

    matcher.reset()
    lane_only = _observation(
        lane=LaneObservation(error=0.0, confidence=0.9))
    matcher.update(lane_only)
    assert matcher.update(lane_only).context_id == "lane_follow"


def test_signal_conflict_freezes_switching():
    matcher = SceneContextMatcher(_store(), enter_frames=3)
    matcher.update(_crosswalk_observation())
    matcher.update(_crosswalk_observation())
    # Conflict frame resets the confirmation counter: no switch yet.
    matcher.update(_crosswalk_observation(conflict=True))
    assert matcher.update(_crosswalk_observation()).context_id \
        == GENERIC_CONTEXT_ID
    assert matcher.update(_crosswalk_observation()).context_id \
        == GENERIC_CONTEXT_ID
    assert matcher.update(_crosswalk_observation()).context_id == "crosswalk"


def test_different_candidate_resets_pending_count():
    matcher = SceneContextMatcher(_store(), enter_frames=3)
    stop = _observation(stop_line=_marking(0.9))
    lane = _observation(lane=LaneObservation(error=0.0, confidence=0.9))
    matcher.update(stop)
    matcher.update(stop)
    matcher.update(lane)  # breaks consecutiveness
    matcher.update(stop)
    matcher.update(stop)
    assert matcher.context_id == GENERIC_CONTEXT_ID
    assert matcher.update(stop).context_id == "stop_line"


def test_matcher_returns_to_generic_after_exit_frames():
    matcher = SceneContextMatcher(_store(), enter_frames=2, exit_frames=3)
    matcher.update(_crosswalk_observation())
    matcher.update(_crosswalk_observation())
    empty = _observation()
    assert matcher.update(empty).context_id == "crosswalk"
    assert matcher.update(empty).context_id == "crosswalk"
    # Confidence holds at the last confirmed value while hysteresis waits.
    assert matcher.scene().confidence == pytest.approx(0.9)
    assert matcher.update(empty).context_id == GENERIC_CONTEXT_ID
    assert matcher.scene().confidence == 0.0


def test_reset_returns_to_generic():
    matcher = SceneContextMatcher(_store(), enter_frames=1)
    matcher.update(_crosswalk_observation())
    assert matcher.context_id == "crosswalk"
    matcher.reset()
    assert matcher.context_id == GENERIC_CONTEXT_ID
    assert matcher.scene().confidence == 0.0


def test_update_rejects_non_observation():
    matcher = SceneContextMatcher(_store())
    with pytest.raises(ValueError):
        matcher.update("not an observation")


def test_matcher_rejects_invalid_frames_config():
    store = _store()
    with pytest.raises(ValueError):
        SceneContextMatcher(store, enter_frames=0)
    with pytest.raises(ValueError):
        SceneContextMatcher(store, exit_frames=True)
    with pytest.raises(ValueError):
        SceneContextMatcher(store, min_confidence=1.5)
