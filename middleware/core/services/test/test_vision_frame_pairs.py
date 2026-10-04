"""A bounded raw/annotated capture pair shares one viewer pull admission."""
import pytest
from core_features.vision import VisionFrameStore, VisionFrameAdvanced, VisionPullRateLimited


def _publish(store, stamp=100., received=10., frame_id='front'):
    common = dict(captured_at=stamp, received_at=received, frame_id=frame_id, source='front', width=8, height=8)
    store.publish_raw(b'\xff\xd8raw\xff\xd9', **common)
    return store.publish(b'\xff\xd8annotation\xff\xd9', overlay='follow-road-v2', **common)


def test_only_same_capture_can_advertise_and_return_raw_counterpart():
    store = VisionFrameStore()
    annotated = _publish(store)
    status = store.status(now=10.)
    assert status['raw_available'] and status['raw_sequence'] == annotated.sequence
    raw = store.frame_for_viewer('a', expected_sequence=annotated.sequence, overlay=False, now=10.)
    assert raw.data == b'\xff\xd8raw\xff\xd9' and raw.overlay == 'none'
    assert (raw.captured_at, raw.frame_id, raw.sequence) == (100., 'front', annotated.sequence)
    store.publish(b'\xff\xd8other\xff\xd9', captured_at=101., received_at=10.1,
                  frame_id='front', source='front')
    assert store.status(now=10.1)['raw_available'] is False


def test_pair_grants_each_variant_once_even_if_latest_advances():
    store = VisionFrameStore()
    first = _publish(store)
    got = store.frame_for_viewer('a', expected_sequence=first.sequence, now=10.)
    _publish(store, stamp=101., received=10.1)
    raw = store.frame_for_viewer('a', expected_sequence=first.sequence, overlay=False, now=10.1)
    assert raw.captured_at == got.captured_at and raw.frame_id == got.frame_id
    for overlay in (False, True):
        with pytest.raises(VisionPullRateLimited):
            store.frame_for_viewer('a', expected_sequence=first.sequence, overlay=overlay, now=10.2)
    with pytest.raises(VisionPullRateLimited):
        store.frame_for_viewer('a', expected_sequence=2, now=10.2)
    assert store.frame_for_viewer('a', expected_sequence=2, now=10.4).captured_at == 101.


def test_raw_requires_exact_frame_id_and_stamp_and_fresh_receipt():
    store = VisionFrameStore()
    _publish(store)
    store.publish(b'\xff\xd8other\xff\xd9', captured_at=100., received_at=10.1,
                  frame_id='another-camera', source='front')
    assert not store.status(now=10.1)['raw_available']
    assert store.frame_for_viewer('a', expected_sequence=2, overlay=False, now=10.1) is None
    assert not store.status(now=12.1)['raw_available']


def test_pair_cache_is_bounded_and_does_not_mix_newest_raw_with_older_annotation():
    store = VisionFrameStore()
    first = _publish(store)
    store.frame_for_viewer('a', expected_sequence=first.sequence, now=10.)
    for i in range(1, 5):
        _publish(store, stamp=100.+i, received=10.+i/10.)
    with pytest.raises(VisionFrameAdvanced):
        store.frame_for_viewer('a', expected_sequence=first.sequence, overlay=False, now=10.5)


def test_repeat_variant_is_not_a_new_admission_when_camera_stops():
    store = VisionFrameStore()
    frame = _publish(store)
    store.frame_for_viewer('a', expected_sequence=frame.sequence, now=10.)
    with pytest.raises(VisionPullRateLimited):
        store.frame_for_viewer('a', expected_sequence=frame.sequence, now=10.5)


def test_raw_pair_with_different_dimensions_is_unavailable():
    store = VisionFrameStore()
    _publish(store)
    store.publish(b'\xff\xd8scaled\xff\xd9', captured_at=100., received_at=10.1,
                  frame_id='front', source='front', width=16, height=8)
    assert not store.status(now=10.1)['raw_available']


def test_delayed_source_quality_expires_by_image_age_not_receipt_alone():
    store = VisionFrameStore()
    store.publish(b'\xff\xd8image\xff\xd9', captured_at=100., received_at=10., frame_id='front',
                  source='front', quality=dict(valid=False, reason='low_light'), source_age_s=1.9)
    assert store.status(now=10.05)['quality'] == dict(valid=False, reason='low_light')
    assert store.status(now=10.11)['available'] and store.status(now=10.11)['quality'] is None
