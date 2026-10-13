"""D-659 object diagnostics on original image boxes; never an approval gate."""
import math
from copy import deepcopy

import numpy as np

from control.sensing.perception.learned.manifest import OBJECT_CLASSES
from core_common.observation import road_region_input_errors
from object_boxes import _check_human_box, _iou


COUNTS = ('true_positive', 'false_positive', 'false_negative', 'small_truth',
          'small_matched', 'occluded_truth', 'occluded_matched',
          'occlusion_unverified_truth')


def _fraction(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1


def _rates(counts):
    tp = counts['true_positive']
    return dict(counts,
        precision=tp / (tp + counts['false_positive']) if tp + counts['false_positive'] else None,
        recall=tp / (tp + counts['false_negative']) if tp + counts['false_negative'] else None,
        small_recall=counts['small_matched'] / counts['small_truth'] if counts['small_truth'] else None,
        occluded_recall=counts['occluded_matched'] / counts['occluded_truth'] if counts['occluded_truth'] else None)


def evaluate_detections(predictions, truth, *, frame_size, match_iou, small_area_fraction,
                        domain='real', conditions=()):
    """Confidence-ordered, best-IoU, same-class one-to-one matching.

    Caller supplies complete reviewed truth and binds provenance. Missing occlusion
    annotation is unknown; small/occluded recall uses full-frame matches, without
    removing predictions that matched other objects. None predictions abstains.
    """
    if (not isinstance(frame_size, (tuple, list)) or len(frame_size) != 2
            or any(type(v) is not int or not 0 < v <= 4096 for v in frame_size)):
        raise ValueError('original frame size must be positive integer width/height')
    if not _fraction(match_iou) or not _fraction(small_area_fraction):
        raise ValueError('fixed metric profile fractions must be in (0, 1]')
    if (not isinstance(domain, str) or domain not in ('real', 'simulation')
            or not isinstance(conditions, (list, tuple))
            or any(not isinstance(c, str) or not c.strip() for c in conditions)
            or len(set(conditions)) != len(conditions)):
        raise ValueError('real/simulation domain and unique named conditions required')
    if not isinstance(truth, list) or (predictions is not None and not isinstance(predictions, list)):
        raise ValueError('truth and predictions must be box lists; None predictions abstains')
    width, height = frame_size
    for rows, predicted in ((truth, False), (predictions or [], True)):
        for row in rows:
            _check_human_box(row)
            x0, y0, x1, y1 = row['bbox_xyxy']
            if row.get('label') not in OBJECT_CLASSES or not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError('box must use a detector class and original image coordinates')
            if predicted:
                confidence = row.get('confidence')
                if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError('prediction confidence must be a finite fraction')
            elif 'occluded' in row and type(row['occluded']) is not bool:
                raise ValueError('reviewed occluded flag must be boolean or absent')
    counts = {name: dict.fromkeys(COUNTS, 0) for name in OBJECT_CLASSES}
    matched = set()
    for pred in sorted(predictions or [], key=lambda row: -row['confidence']):
        candidates = [(i, _iou(pred['bbox_xyxy'], row['bbox_xyxy']))
                      for i, row in enumerate(truth) if i not in matched and row['label'] == pred['label']]
        best = max(candidates, key=lambda item: item[1], default=None)
        if best is not None and best[1] >= match_iou:
            matched.add(best[0])
            counts[pred['label']]['true_positive'] += 1
        else:
            counts[pred['label']]['false_positive'] += 1
    for i, row in enumerate(truth):
        metric = counts[row['label']]
        metric['false_negative'] += i not in matched
        x0, y0, x1, y1 = row['bbox_xyxy']
        if (x1 - x0) * (y1 - y0) <= width * height * small_area_fraction:
            metric['small_truth'] += 1
            metric['small_matched'] += i in matched
        if row.get('occluded') is True:
            metric['occluded_truth'] += 1
            metric['occluded_matched'] += i in matched
        elif 'occluded' not in row:
            metric['occlusion_unverified_truth'] += 1
    return dict(fitness_verdict='HOLD', domain=domain, conditions=list(conditions),
                profile=dict(match_iou=match_iou, small_area_fraction=small_area_fraction),
                inference_abstained=predictions is None,
                classes={name: _rates(metric) for name, metric in counts.items()})


def evaluate_model_frame(model, bgr, image_snapshot, truth, *, now_ns, max_age_ns,
                         match_iou, small_area_fraction, domain='real', conditions=()):
    """Use ObjectDetModel's existing letterbox/decode/NMS; truth never enters infer."""
    if (not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8 or bgr.ndim != 3
            or bgr.shape[2] != 3 or not bgr.size):
        raise ValueError('expected a non-empty uint8 HxWx3 BGR frame')
    if (model.manifest.task != 'object_det'
            or tuple(c['name'] for c in model.manifest.raw['output']['classes']) != OBJECT_CLASSES):
        raise ValueError('D-602 six-class object detector required')
    parameters = dict(frame_size=(bgr.shape[1], bgr.shape[0]), match_iou=match_iou,
                      small_area_fraction=small_area_fraction, domain=domain, conditions=conditions)
    report = evaluate_detections(None, truth, **parameters)
    errors = [e for e in road_region_input_errors(image_snapshot, image_snapshot,
              now_ns=now_ns, max_age_ns=max_age_ns) if e.startswith('image_') and e != 'image_reference_missing']
    latency = None
    if not errors:
        result = model.infer(bgr)
        if (result.model_revision != model.manifest.model_revision
                or type(result.latency_ms) not in (int, float)
                or not math.isfinite(result.latency_ms) or result.latency_ms < 0):
            raise ValueError('detector result revision or latency differs')
        report = evaluate_detections(result.detections, truth, **parameters)
        latency = result.latency_ms
    return dict(report, input_errors=errors, image_snapshot_id=image_snapshot.snapshot_id,
                model_revision=model.manifest.model_revision,
                camera_profile_revision=model.manifest.camera_profile_revision,
                preprocessing=deepcopy(model.manifest.raw['input']),
                source_shape=list(bgr.shape[:2]), infer_latency_ms=latency,
                detector_thresholds=dict(confidence=model._conf, nms_iou=model._iou))


def summarize_frames(reports):
    """Pool counts, separately by domain/condition; never average frame recall."""
    if not isinstance(reports, list) or not reports:
        raise ValueError('non-empty frame report list required')
    profile = reports[0]['profile']
    if any(row['profile'] != profile for row in reports):
        raise ValueError('cannot pool different metric profiles')
    binding_keys = ('model_revision', 'camera_profile_revision', 'preprocessing', 'detector_thresholds')
    binding = {key: reports[0][key] for key in binding_keys if key in reports[0]}
    if binding and len(binding) != len(binding_keys):
        raise ValueError('incomplete model binding')
    for row in reports:
        if {key: row[key] for key in binding_keys if key in row} != binding:
            raise ValueError('cannot pool different or missing model bindings')
        if row['domain'] not in ('real', 'simulation'):
            raise ValueError('invalid report domain')
    def pool(rows):
        return dict(frames=len(rows), inference_abstained_frames=sum(r['inference_abstained'] for r in rows),
                    classes={name: _rates({key: sum(r['classes'][name][key] for r in rows)
                                          for key in COUNTS}) for name in OBJECT_CLASSES})
    domains = {domain: [r for r in reports if r['domain'] == domain] for domain in ('real', 'simulation')}
    return dict(fitness_verdict='HOLD', profile=deepcopy(profile), bindings=deepcopy(binding),
                domains={domain: pool(rows) for domain, rows in domains.items()},
                conditions={domain: {condition: pool([r for r in rows if condition in r['conditions']])
                                     for condition in sorted({c for r in rows for c in r['conditions']})}
                            for domain, rows in domains.items()})
