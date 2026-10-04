"""BurstGate: corroboration-or-operator trigger; vision alone never bursts."""
import pytest

from control.control.burst_gate import burst_gate
from control.control.detection_evidence import DetectionEvidence


def evidence(seq=41, observed_at=1000.0, detections=None):
    person = [{'label': 'person', 'x': 0.4, 'y': 0.3, 'w': 0.2, 'h': 0.4,
               'confidence': 0.8, 'track_id': 3}]
    packet = {
        'model_revision': 'yolo11n-r1',
        'observed_at': observed_at,
        'seq': seq,
        'input_width': 640,
        'input_height': 640,
        'input_fps': 10.0,
        'inference_ms': 12.0,
        'detections': person if detections is None else detections,
    }
    return DetectionEvidence.capture(packet, source_now=1000.0, received_at=10.0)


def gate(evidence_=None, now=10.01, previous_seq=None, metric=True, operator=False):
    return burst_gate(evidence_ if evidence_ is not None else evidence(),
                      now, previous_seq,
                      metric_obstacle_fresh=metric, operator_request=operator)


def test_operator_request_bursts_without_vision_or_metric():
    # Operator authority stands above the sequence; stale vision is irrelevant.
    assert gate(evidence(), operator=True) == {'burst': True,
                                               'reason': 'operator_request'}
    assert gate(evidence(), now=99.0, operator=True)['burst'] is True


def test_corroborated_fresh_detection_bursts():
    assert gate() == {'burst': True, 'reason': 'corroborated'}


def test_vision_alone_never_bursts():
    # THE D-137 rule: a box alone spends nobody's bandwidth.
    assert gate(metric=False) == {'burst': False, 'reason': 'vision_only'}


def test_metric_alone_and_absence_do_not_burst():
    # LiDAR sees something, YOLO sees nothing: no vision-triggered burst.
    empty = evidence(detections=[])
    assert gate(empty) == {'burst': False, 'reason': 'no_detection'}
    assert gate(empty, metric=False) == {'burst': False, 'reason': 'no_detection'}


def test_missed_frames_are_not_absence_and_do_not_burst():
    # seq 43 after 41: two frames nobody saw. "Not seen" is not "not there",
    # so a gap packet cannot trigger even with metric corroboration.
    gap = evidence(seq=43, detections=[])
    assert gate(gap, previous_seq=41) == {'burst': False,
                                          'reason': 'vision_missed'}
    assert gate(gap, previous_seq=41, metric=True)['burst'] is False


def test_stale_and_invalid_evidence_do_not_burst():
    assert gate(evidence(), now=10.5) == {'burst': False,
                                          'reason': 'vision_stale'}
    from dataclasses import replace
    broken = replace(evidence(), detections_json='not json')
    assert gate(broken) == {'burst': False, 'reason': 'vision_invalid'}


def test_gate_inputs_are_typed():
    with pytest.raises(ValueError):
        gate(metric='yes')
    with pytest.raises(ValueError):
        gate(operator=1)
    with pytest.raises(ValueError):
        burst_gate({'status': 'fresh'}, 10.0, metric_obstacle_fresh=True,
                   operator_request=False)
