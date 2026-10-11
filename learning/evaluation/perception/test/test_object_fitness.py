"""D-659 object metrics; synthetic boxes are not independent acceptance."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
for holder in ('middleware/perception', 'learning/curation/perception',
               'learning/evaluation/perception', 'contracts/foundation'):
    sys.path.insert(0, str(ROOT / holder))

from object_fitness import evaluate_detections, summarize_frames


def box(label='person', xyxy=(0, 0, 10, 10), **kwargs):
    return dict(label=label, bbox_xyxy=list(xyxy), **kwargs)


def score(predictions, truth, **kwargs):
    return evaluate_detections(predictions, truth, frame_size=(100, 100),
                               match_iou=.5, small_area_fraction=.02, **kwargs)


def test_duplicates_wrong_classes_and_missing_truth_are_counted():
    truth = [box(occluded=True), box('cone', (50, 50, 90, 90))]
    report = score([box(confidence=.9), box(confidence=.8),
                    box('robot', (50, 50, 90, 90), confidence=.7)], truth)
    assert report['classes']['person']['true_positive'] == 1
    assert report['classes']['person']['false_positive'] == 1
    assert report['classes']['person']['precision'] == .5
    assert report['classes']['cone']['false_negative'] == 1
    assert report['classes']['robot']['false_positive'] == 1
    assert report['classes']['person']['small_truth'] == 1
    assert report['classes']['person']['small_recall'] == 1
    assert report['classes']['person']['occluded_recall'] == 1
    assert report['classes']['cone']['occlusion_unverified_truth'] == 1
    assert report['fitness_verdict'] == 'HOLD'


def test_confidence_order_matches_each_truth_once_with_best_iou():
    truth = [box(xyxy=(0, 0, 10, 10)), box(xyxy=(5, 0, 15, 10))]
    report = score([box(xyxy=(0, 0, 12, 10), confidence=.9),
                    box(xyxy=(0, 0, 10, 10), confidence=.8)], truth)
    assert report['classes']['person']['true_positive'] == 1
    assert report['classes']['person']['false_negative'] == 1


def test_empty_reviewed_frame_counts_false_positives_without_inventing_recall():
    metric = score([box(confidence=.9)], [])['classes']['person']
    assert metric['false_positive'] == 1 and metric['precision'] == 0
    assert metric['recall'] is None and metric['occluded_recall'] is None


def test_abstention_keeps_truth_and_misses_in_denominators():
    report = score(None, [box(occluded=True)])
    metric = report['classes']['person']
    assert report['inference_abstained'] is True
    assert metric['false_negative'] == metric['small_truth'] == metric['occluded_truth'] == 1
    assert metric['recall'] == metric['small_recall'] == metric['occluded_recall'] == 0
    assert metric['precision'] is None


@pytest.mark.parametrize('bad', [box('person_feet'), box('obstacle'),
    box(xyxy=(-1, 0, 10, 10)), box(xyxy=(0, 0, 101, 10)),
    box(xyxy=(0, 0, 0, 10)), box(xyxy=(False, 0, 10, 10)),
    box(xyxy=(0, 0, float('nan'), 10)), box(occluded='true')])
def test_invalid_truth_is_refused(bad):
    with pytest.raises(ValueError):
        score([], [bad])


@pytest.mark.parametrize('confidence', [None, True, -1, 2, float('inf')])
def test_invalid_prediction_confidence_is_refused(confidence):
    with pytest.raises(ValueError):
        score([box(confidence=confidence)], [])


@pytest.mark.parametrize('parameter,value', [('match_iou', 0), ('match_iou', True),
    ('match_iou', float('nan')), ('small_area_fraction', 0), ('small_area_fraction', 2)])
def test_invalid_fixed_metric_parameters_are_refused(parameter, value):
    kwargs = dict(frame_size=(100, 100), match_iou=.5, small_area_fraction=.02)
    kwargs[parameter] = value
    with pytest.raises(ValueError):
        evaluate_detections([], [], **kwargs)


def test_pooled_counts_preserve_domains_conditions_and_abstention():
    first = score([box(confidence=.9)], [box()], domain='real', conditions=['glare'])
    second = score(None, [box(), box('person', (20, 20, 30, 30))],
                   domain='real', conditions=['glare'])
    sim = score([box(confidence=.9)], [box()], domain='simulation', conditions=[])
    summary = summarize_frames([first, second, sim])
    real = summary['domains']['real']
    assert real['classes']['person']['recall'] == pytest.approx(1 / 3)
    assert real['inference_abstained_frames'] == 1 and real['frames'] == 2
    assert summary['domains']['simulation']['classes']['person']['recall'] == 1
    assert summary['conditions']['real']['glare'] == real


def test_summary_cannot_pool_different_metric_profiles():
    first = score([], [])
    second = evaluate_detections([], [], frame_size=(100, 100), match_iou=.75,
                                 small_area_fraction=.02)
    with pytest.raises(ValueError, match='profile'):
        summarize_frames([first, second])
