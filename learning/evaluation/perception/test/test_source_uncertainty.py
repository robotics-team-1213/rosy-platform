from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for holder in ('middleware/perception', 'contracts/foundation', 'learning/evaluation/perception'):
    sys.path.insert(0, str(ROOT / holder))

from core_common.observation import ObservationSnapshot, SnapshotValidity
from road_fitness import evaluate_frame


def report(identity, group, *, hit=True, domain='real', invalid=False, unknown=False):
    image = ObservationSnapshot(identity, 'camera', 1000, datetime.now(timezone.utc),
                                'camera', 'cal', ('capture',), SnapshotValidity.VALID, 'tf')
    anchor = ObservationSnapshot(identity + '-anchor', 'pose', 1000, image.received_at,
                                 'camera', 'cal', (identity,),
                                 SnapshotValidity.INVALID if invalid else SnapshotValidity.VALID, 'tf')
    classes = [{'index': 0, 'name': 'background', 'role': 'background'},
               {'index': 1, 'name': 'drivable', 'role': 'drivable', 'semantic': 'road_surface/1'}]
    labels = np.array([[1 if hit else 0, 0]], dtype=np.uint8)
    truth = np.array([[255, 255] if unknown else [1, 0]], dtype=np.uint8)
    return {**evaluate_frame(labels, classes, image, anchor, [[0, 0]], truth, truth,
                            domain=domain, conditions=['junction'], now_ns=1050, max_age_ns=100),
            'identity': identity, 'session': group + '-session', 'capture_group': group}


def summarize(rows):
    from source_uncertainty import summarize_sources
    return summarize_sources(rows)


def test_bootstrap_samples_whole_capture_groups_and_preserves_weighted_counts():
    rows = [report('a1', 'a'), report('a2', 'a'), report('b1', 'b', hit=False)]
    result = summarize(rows)
    real = result['domains']['real']
    assert result['method'] == 'capture-group-percentile-bootstrap/1'
    assert result['resamples'] == 1000 and result['seed'] == 0
    assert real['source_count'] == 2
    assert real['sources']['a']['frames'] == 2
    assert real['point']['road_surface']['iou'] == pytest.approx(2 / 3)
    interval = real['intervals']['road_surface']['iou']
    assert interval['bounds'] == [0, 1] and interval['valid_resamples'] == 1000
    assert real['intervals']['current_region']['frame_coverage']['bounds'][0] == 0
    assert result['domains']['simulation']['source_count'] == 0
    assert result['conditions']['real']['junction']['source_count'] == 2
    assert result['fitness_verdict'] == 'HOLD'
    assert summarize(list(reversed(rows))) == result


def test_single_source_does_not_turn_many_frames_into_independent_samples():
    one = summarize([report('a1', 'a'), report('a2', 'a')])['domains']['real']
    assert one['source_count'] == 1
    assert one['intervals']['road_surface']['iou']['bounds'] is None
    assert one['intervals']['road_surface']['iou']['reason'] == 'insufficient_sources'


def test_abstention_and_unknown_truth_keep_coverage_denominators():
    real = summarize([report('a', 'a', invalid=True), report('b', 'b', invalid=True)])['domains']['real']
    assert real['point']['current_region']['abstained_frames'] == 2
    assert real['intervals']['current_region']['frame_coverage']['bounds'] == [0, 0]
    assert real['intervals']['current_region']['iou']['reason'] == 'undefined_resamples'
    unknown = summarize([report('a', 'a', unknown=True), report('b', 'b', unknown=True)])['domains']['real']
    assert unknown['point']['road_surface']['unknown_truth_pixels'] == 4
    assert unknown['intervals']['road_surface']['full_grid_pixel_coverage']['bounds'] is None
    mixed = summarize([report('a', 'a'), report('b', 'b', unknown=True)])['domains']['real']
    assert 0 < mixed['intervals']['road_surface']['iou']['valid_resamples'] < 1000
    assert mixed['intervals']['road_surface']['iou']['bounds'] is None


@pytest.mark.parametrize('field,value', [('identity', ''), ('identity', True), ('session', ''),
                                        ('capture_group', ''), ('capture_group', ' a '),
                                        ('domain', 'other')])
def test_unbound_or_malformed_source_is_rejected(field, value):
    row = report('a', 'a')
    row[field] = value
    with pytest.raises(ValueError):
        summarize([row])


def test_duplicate_identity_and_source_domain_or_session_conflicts_are_rejected():
    with pytest.raises(ValueError):
        summarize([report('a', 'a'), report('a', 'b')])
    with pytest.raises(ValueError):
        summarize([report('a', 'a'), report('b', 'a', domain='simulation')])
    row = report('b', 'b')
    row['session'] = 'a-session'
    with pytest.raises(ValueError):
        summarize([report('a', 'a'), row])


def test_empty_diagnostic_has_no_interval():
    result = summarize([])
    assert result['domains']['real']['source_count'] == 0
    assert result['domains']['real']['intervals']['road_surface']['iou']['bounds'] is None
    assert result['fitness_verdict'] == 'HOLD'


def test_point_boundary_float_sum_uses_stable_identity_order():
    rows = [report('a', 'a'), report('b', 'b'), report('c', 'c')]
    for row, distance in zip(rows, (1e16, 1.0, 1.0)):
        for target in ('road_surface', 'current_region'):
            row[target].update(boundary_reason='ok', boundary_truth_pixels=1,
                               boundary_predicted_pixels=1, boundary_distance_sum_px=distance)
    assert summarize(rows) == summarize(list(reversed(rows)))
