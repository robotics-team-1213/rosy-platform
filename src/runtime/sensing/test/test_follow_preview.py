"""Camera explanations must use the frame's evidence, never stale guesses."""
import cv2
import numpy as np
import pytest

from control.sensing.perception.follow_preview import FrameEvidence, draw_follow_evidence, predicted_road


def test_evidence_matches_capture_stamp_and_survives_callback_reordering():
    cache = FrameEvidence()
    cache.add('keep', {'stamp': 2.0, 'strategy': 'both'})
    cache.add('objects', {'stamp': 1.0, 'regions': []})
    assert cache.for_frame('keep', 1.0) is None
    assert cache.for_frame('keep', 2.0)['strategy'] == 'both'
    assert cache.for_frame('objects', 2.0) is None
    cache.add('objects', {'stamp': 2.0, 'regions': []})
    assert cache.for_frame('objects', 2.0) is not None
    assert cache.for_frame('keep', 2.1) is None


@pytest.mark.parametrize('stamp', [None, True, float('nan'), float('inf'), '2'])
def test_invalid_stamp_cannot_join_a_frame(stamp):
    cache = FrameEvidence()
    cache.add('keep', {'stamp': stamp})
    assert cache.for_frame('keep', 2.0) is None


def test_cache_has_a_bounded_frame_history():
    cache = FrameEvidence()
    for stamp in range(100):
        cache.add('keep', {'stamp': float(stamp)})
    assert cache.for_frame('keep', 0.0) is None
    assert cache.for_frame('keep', 99.0) is not None


def test_delayed_callback_prefers_completed_frame_but_never_stale_history():
    cache = FrameEvidence()
    cache.add('keep', {'stamp': 1.0})
    frames = [(None, None, None, 1.0), (None, None, None, 1.1)]
    assert cache.select_frame(frames)[3] == 1.0
    frames.append((None, None, None, 2.0))
    assert cache.select_frame(frames)[3] == 2.0


def test_non_keep_camera_line_shows_direction_without_fabricated_target(monkeypatch):
    texts = []
    monkeypatch.setattr(cv2, 'putText', lambda img, text, *a, **kw: texts.append(text))
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1, line={
        'source': 'CAMERA_LINE', 'visible': True, 'error': -.4, 'confidence': .7})
    assert any('FOLLOW LEFT' in t for t in texts)
    assert 'TARGET' not in texts


def test_selected_boundaries_target_and_objects_are_visible(monkeypatch):
    texts = []
    real_text = cv2.putText
    def capture(img, text, *args, **kwargs):
        texts.append(text)
        return real_text(img, text, *args, **kwargs)
    monkeypatch.setattr(cv2, 'putText', capture)
    image = np.zeros((240, 320, 3), np.uint8)
    draw_follow_evidence(image, scale=1.0, keep={
        'strategy': 'both', 'error': .3, 'confidence': .85,
        'target_px': [205, 130], 'target_m': [.25, -.06],
        'boundaries': [
            {'side': 'left', 'selected': True, 'ends_px': [[40, 220], [100, 80]]},
            {'side': 'right', 'selected': True, 'ends_px': [[270, 220], [210, 80]]}],
        'candidates': [{'rejected': True, 'reason': 'transverse',
                        'ends_px': [[100, 110], [180, 110]]}],
    }, objects={'image_size': [320, 240], 'quality': {'valid': True},
                'regions': [{'b': [225, 50, 290, 105], 'n': 1, 'k': 'f'}]})
    assert any('FOLLOW RIGHT' in t for t in texts)
    assert any('85%' in t for t in texts)
    assert 'LEFT LANE' in texts and 'RIGHT LANE' in texts
    assert 'FOLLOW PATH' in texts
    assert any('OBJ 1' in t and 'UNKNOWN' in t for t in texts)
    assert any('unranged' in t for t in texts)
    assert any('transverse' in t for t in texts)
    assert np.any(np.all(image == (60, 220, 60), axis=2))
    assert np.any(np.all(image == (230, 60, 230), axis=2))
    assert np.any(np.all(image == (0, 140, 255), axis=2))


def test_hold_discards_target_and_missing_objects_do_not_mean_clear(monkeypatch):
    texts = []
    monkeypatch.setattr(cv2, 'putText', lambda img, text, *a, **kw: texts.append(text))
    image = np.zeros((240, 320, 3), np.uint8)
    draw_follow_evidence(image, scale=1, keep={
        'strategy': 'none', 'reason': 'junction', 'target_px': [200, 100]}, objects=None)
    assert any('HOLD' in t and 'junction' in t for t in texts)
    assert any('OBJECTS: unavailable' in t for t in texts)
    assert not np.any(np.all(image[:180] == (230, 60, 230), axis=2))


def test_invalid_and_offscreen_geometry_does_not_crash_or_draw_a_target():
    image = np.zeros((240, 320, 3), np.uint8)
    draw_follow_evidence(image, scale=.5, keep={
        'strategy': 'both', 'error': float('nan'), 'confidence': .8,
        'target_px': [float('inf'), 100],
        'boundaries': [{'ends_px': [None, [1, 2]]}],
    }, objects={'image_size': [0, 240], 'quality': {'valid': True},
                'regions': [{'b': [1, 2, 3]}]})
    assert not np.any(np.all(image[:180] == (230, 60, 230), axis=2))


def test_prediction_uses_existing_shadow_state_in_robot_coordinates():
    samples = predicted_road({'level': 'TRACK', 'd': .02, 'phi': .1,
                              'kappa': 1.0, 'w': .185, 'calibration_suspect': False})
    assert samples is not None
    x, y = samples[-1]
    assert x == pytest.approx(.33)
    assert y == pytest.approx(-.02 - .33 * .1 + .5 * .33 ** 2)


@pytest.mark.parametrize('patch', [
    {'level': 'STOP'}, {'level': 'unknown'}, {'calibration_suspect': True},
    {'d': float('nan')}, {'w': -1}, {'phi': None},
])
def test_prediction_is_hidden_on_stop_or_invalid_calibration(patch):
    state = dict(level='TRACK', d=0., phi=0., kappa=0., w=.185)
    state.update(patch)
    assert predicted_road(state) is None


def test_tag_label_never_becomes_a_robot_name_or_a_metric_range(monkeypatch):
    texts = []
    monkeypatch.setattr(cv2, 'putText', lambda img, text, *a, **kw: texts.append(text))
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1,
                         tags=[{'tag_id': 7, 'corners_px': [[20, 50], [60, 50], [60, 90], [20, 90]]}])
    assert any('TAG 7' in t for t in texts)
    assert not any('ROBOT' in t or 'PERSON' in t or 'DOCK' in t for t in texts)


def test_multiple_boundaries_without_selection_cannot_be_labelled_selected(monkeypatch):
    texts = []
    monkeypatch.setattr(cv2, 'putText', lambda img, text, *a, **kw: texts.append(text))
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1, keep={
        'strategy': 'none', 'reason': 'junction', 'boundaries': [
            {'side': 'left', 'ends_px': [[40, 180], [100, 80]]},
            {'side': 'right', 'ends_px': [[270, 180], [210, 80]]}]})
    assert any('LEFT LANE: UNSEEN' in t for t in texts)
    assert any('RIGHT LANE: UNSEEN' in t for t in texts)
    assert 'FOLLOW PATH' not in texts
