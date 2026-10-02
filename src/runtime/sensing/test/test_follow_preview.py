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


@pytest.mark.parametrize('record,label', [
    ({'b': [20, 150, 60, 200], 'n': 0, 'k': 'f', 'm': 0.42, 's': 'L'}, 'OBJ 1 UNKNOWN 0.42m L'),
    ({'b': [20, 150, 60, 200], 'n': 1, 'k': 'd', 'm': 0.3, 's': 'G'}, 'OBJ 1 DARK 0.30m G NEAR'),
    ({'b': [20, 150, 60, 200], 'n': 0, 'k': 'f', 'm': 0.3}, 'OBJ 1 UNKNOWN 0.30m'),
    ({'b': [20, 150, 60, 200], 'n': 0, 'k': 'f', 's': 'L'}, 'OBJ 1 UNKNOWN unranged'),
    ({'b': [20, 150, 60, 200], 'n': 0, 'k': 'f', 'm': 0.3, 's': 'X'}, 'OBJ 1 UNKNOWN 0.30m'),
])
def test_object_badge_names_the_range_source(monkeypatch, record, label):
    """D-423: L = LiDAR, G = ground plane; no source letter is invented."""
    texts = []
    real_text = cv2.putText
    def capture(img, text, *args, **kwargs):
        texts.append(text)
        return real_text(img, text, *args, **kwargs)
    monkeypatch.setattr(cv2, 'putText', capture)
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1.0, objects={
        'image_size': [320, 240], 'quality': {'valid': True}, 'regions': [record]})
    assert label in texts


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


# --- D-423 §2.3: detections on the overlay, paired with regions for display only ---

from control.sensing.perception.follow_preview import DETECTION_MIN_IOU, pair_detections  # noqa: E402


def _texts(monkeypatch):
    texts = []
    real_text = cv2.putText
    def capture(img, text, *args, **kwargs):
        texts.append(text)
        return real_text(img, text, *args, **kwargs)
    monkeypatch.setattr(cv2, 'putText', capture)
    return texts


def _detections(*boxes, ranges=None):
    doc = {'observed_at': 5.0, 'seq': 1, 'model_revision': 'object-det-r1', 'input_width': 320,
           'input_height': 240, 'input_fps': 8.0,
           'detections': [{'label': label, 'x': x / 320, 'y': y / 240, 'w': w / 320, 'h': h / 240,
                           'confidence': 0.9} for label, x, y, w, h in boxes]}
    if ranges is not None:
        doc['ranges'] = ranges
    return doc


def test_pairing_takes_the_best_overlap_once_and_ignores_weak_overlap():
    regions = [{'b': [20, 150, 60, 200]}, {'b': [200, 100, 260, 160]}, {'b': [0, 0, 10, 10]}]
    detections = _detections(('cone', 22, 152, 38, 48), ('robot', 205, 100, 50, 60),
                             ('sign', 2, 2, 60, 60))
    assert pair_detections(regions, detections['detections'], (320, 240)) == {0: 0, 1: 1}
    assert 0 < DETECTION_MIN_IOU < 1


def test_paired_region_shows_the_class_and_the_detection_range(monkeypatch):
    texts = _texts(monkeypatch)
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1.0, objects={
        'image_size': [320, 240], 'quality': {'valid': True},
        'regions': [{'b': [20, 150, 60, 200], 'n': 0, 'k': 'f', 'm': 0.5, 's': 'G'}]},
        detections=_detections(('cone', 22, 152, 38, 48), ranges=[{'m': 0.42, 's': 'L'}]))
    assert 'OBJ 1 cone 0.42m L' in texts


def test_unpaired_detection_is_drawn_on_its_own(monkeypatch):
    texts = _texts(monkeypatch)
    image = np.zeros((240, 320, 3), np.uint8)
    draw_follow_evidence(image, scale=1.0, objects={
        'image_size': [320, 240], 'quality': {'valid': True}, 'regions': []},
        detections=_detections(('robot', 200, 100, 60, 60), ranges=[None]))
    assert 'DET robot unranged' in texts
    assert any('1 detected' in t for t in texts)


def test_detections_of_another_frame_size_are_not_drawn(monkeypatch):
    texts = _texts(monkeypatch)
    doc = _detections(('robot', 200, 100, 60, 60))
    doc['input_width'] = 640
    draw_follow_evidence(np.zeros((240, 320, 3), np.uint8), scale=1.0, objects={
        'image_size': [320, 240], 'quality': {'valid': True}, 'regions': []}, detections=doc)
    assert not any(t.startswith('DET') for t in texts)


def test_recent_detection_joins_a_later_frame_within_the_window():
    evidence = FrameEvidence()
    evidence.add('detections', _detections(('cone', 1, 1, 5, 5)))     # observed_at 5.0
    assert evidence.recent('detections', 5.4, .6)['seq'] == 1
    assert evidence.recent('detections', 5.7, .6) is None
    assert evidence.recent('detections', 4.9, .6) is None             # never from the future
