"""DetectionEvidence: advisory packet freezing and status-only evaluation."""
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from control.control.detection_evidence import DetectionEvidence


def packet(seq=41, observed_at=1000.0, detections=None, **overrides):
    body = {
        'model_revision': 'yolo11n-r1',
        'observed_at': observed_at,
        'seq': seq,
        'input_width': 640,
        'input_height': 640,
        'input_fps': 10.0,
        'inference_ms': 12.0,
        'detections': [
            {'label': 'person', 'x': 0.4, 'y': 0.3, 'w': 0.2, 'h': 0.4,
             'confidence': 0.8, 'track_id': 3},
        ] if detections is None else detections,
    }
    body.update(overrides)
    return body


def captured(**kw):
    # source 1000.0 received at 10.0: the D-137 example clock shift.
    return DetectionEvidence.capture(packet(**kw), source_now=1000.0,
                                     received_at=10.0)


def test_capture_freezes_packet_and_translates_clock():
    evidence = captured()
    assert evidence.observed_at == 1000.0
    assert evidence.observed_at_mono == 10.0
    assert evidence.model_revision == 'yolo11n-r1'
    assert json.loads(evidence.detections_json) == packet()['detections']
    with pytest.raises(FrozenInstanceError):
        evidence.seq = 42


def test_capture_normalizes_and_drops_unknown_keys():
    # x + w is exactly 1.0 here: a boundary box stays valid.
    evidence = captured(detections=[
        {'label': 'person', 'x': 0.9, 'y': 0.3, 'w': 0.1, 'h': 0.4,
         'confidence': 0.8, 'track_id': 3, 'future_field': 'dropped'},
    ])
    box = json.loads(evidence.detections_json)[0]
    assert box == {'label': 'person', 'x': 0.9, 'y': 0.3, 'w': 0.1, 'h': 0.4,
                   'confidence': 0.8, 'track_id': 3}


def test_capture_rejects_invalid_packets():
    person = packet()['detections'][0]
    bad_packets = [
        None,
        packet(model_revision=''),
        packet(model_revision=' padded'),
        packet(model_revision='r' * 129),
        packet(observed_at=-1.0),
        packet(observed_at=float('nan')),
        packet(observed_at='1000'),
        packet(seq=-1),
        packet(seq=True),
        packet(seq=41.0),
        packet(input_width=4),
        packet(input_width=640.0),
        packet(input_height=4097),
        packet(input_fps=0),
        packet(input_fps=float('inf')),
        packet(inference_ms=-1.0),
        packet(detections='box'),
        packet(detections=[person] * 65),
        packet(detections=[dict(person, label='')]),
        packet(detections=[dict(person, confidence=1.5)]),
        packet(detections=[dict(person, confidence=float('nan'))]),
        packet(detections=[dict(person, x=-0.1)]),
        packet(detections=[dict(person, x=0.5, w=0.6)]),
        packet(detections=[dict(person, w=0.0)]),
        packet(detections=[dict(person, h=0.0)]),
        packet(detections=[dict(person, track_id=-1)]),
        packet(detections=[dict(person, track_id=3.0)]),
    ]
    for body in bad_packets:
        with pytest.raises(ValueError):
            DetectionEvidence.capture(body, source_now=1000.0, received_at=10.0)
    with pytest.raises(ValueError):
        DetectionEvidence.capture(packet(), source_now=float('nan'),
                                  received_at=10.0)


def test_evaluate_fresh_packet_reports_detections():
    result = captured().evaluate(10.01)
    assert result['status'] == 'fresh'
    assert result['detections'] == packet()['detections']
    assert result['age_ms'] == 10.0
    assert result['seq'] == 41
    assert result['model_revision'] == 'yolo11n-r1'


def test_evaluate_empty_and_missed_are_different_facts():
    # Contiguous seq with no detections: nothing was there.
    assert captured(detections=[], seq=42).evaluate(10.01, 41)['status'] == 'empty'
    # Seq jumped past unseen frames with no detections: frames were lost.
    assert captured(detections=[], seq=43).evaluate(10.01, 41)['status'] == 'missed'
    # Boxes are evidence of their own moment even across a gap.
    assert captured(seq=43).evaluate(10.01, 41)['status'] == 'fresh'


def test_evaluate_stale_rejects_age_and_regressed_sequence():
    assert captured().evaluate(10.4)['status'] == 'stale'
    assert captured().evaluate(9.9)['status'] == 'stale'
    assert captured(seq=5).evaluate(10.01, 9)['status'] == 'stale'
    # Just inside and just outside the 300 ms window (D-136): the exact edge
    # is float noise, so the usable claim is tested on both sides of it.
    assert captured().evaluate(10.29)['status'] == 'fresh'
    assert captured().evaluate(10.31)['status'] == 'stale'


def test_evaluate_invalid_snapshot_fails_closed():
    evidence = captured()
    assert replace(evidence, detections_json='not json').evaluate(10.01)['status'] == 'invalid'
    assert replace(evidence, seq=-1).evaluate(10.01)['status'] == 'invalid'
    assert replace(evidence, observed_at_mono=float('nan')).evaluate(10.01)['status'] == 'invalid'
    assert replace(evidence, model_revision='').evaluate(10.01)['status'] == 'invalid'
    assert evidence.evaluate(float('nan'))['status'] == 'invalid'


def test_to_wire_reconstructs_the_source_packet():
    wire = captured().to_wire()
    assert wire == packet()
    bare = DetectionEvidence.capture(
        packet(inference_ms=None), source_now=1000.0, received_at=10.0)
    assert bare.to_wire() == packet(inference_ms=None)


def test_wire_packet_matches_core_common_schema():
    """D-18: the snapshot's packet is the core_common wire truth exactly.

    Test-only import: production control stays unaware of core_common (D-64).
    The wire truth lives in core_common.protocol.detections, not schemas.
    """
    pydantic = pytest.importorskip('pydantic')
    detections = pytest.importorskip('core_common.protocol.detections')
    wire = captured().to_wire()
    model = detections.DetectionEvidence.model_validate(wire)
    assert model.model_dump() == wire
    with pytest.raises(pydantic.ValidationError):
        detections.DetectionEvidence.model_validate(
            dict(wire, detections=[dict(wire['detections'][0], confidence=1.5)]))


def test_box_rules_agree_with_core_common_schema():
    """D-18: the producer gate and the wire truth accept the same boxes."""
    pydantic = pytest.importorskip('pydantic')
    detections = pytest.importorskip('core_common.protocol.detections')
    base = {'label': 'person', 'y': 0.3, 'h': 0.4, 'confidence': 0.8}
    for override in ({'x': 0.9, 'w': 0.1},      # boundary sum is exactly 1.0
                     {'x': 0.0, 'w': 1.0},
                     {'x': 0.5, 'w': 0.6},      # 1.1 -- outside the frame
                     {'x': -0.1, 'w': 0.4},
                     {'w': 0.0},
                     {'h': 1.1}):
        box = dict(base, **override)
        try:
            DetectionEvidence.capture(packet(detections=[box]),
                                      source_now=1000.0, received_at=10.0)
            producer_ok = True
        except ValueError:
            producer_ok = False
        try:
            detections.Detection.model_validate(box)
            wire_ok = True
        except pydantic.ValidationError:
            wire_ok = False
        assert producer_ok == wire_ok, override
