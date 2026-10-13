"""D-673 truth-free file diagnostics; no device delivery, admission or commands."""
from pathlib import Path
import hashlib
import json
import math

from road_fitness_replay import _snapshot
import cv2
import numpy as np
import store
from review_evidence import safe_file, valid_digest
from control.sensing.perception.learned.manifest import load_manifest, verify_files, _parse_input, check_revision
from control.sensing.perception.learned.runner import LaneSegModel
from control.sensing.perception.learned.road_observation import observe_model_frame
from control.sensing.perception.learned.road_region import road_masks, observed_road_region
from core_common.observation import road_region_input_errors

INPUT_SCHEMA = 'rosy.perception.road-observation-input/1'
SCHEMA = 'rosy.perception.road-observation-artifact/1'
INPUT_FIELDS = {'schema', 'model_manifest_sha256', 'image', 'image_sha256',
                'image_snapshot', 'anchor_snapshot', 'seed_pixels', 'now_ns'}
PIXEL_LIMIT = 1_000_000
BYTE_LIMIT = 64 * 1024 * 1024


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(model_folder, *, inputs, max_age_ns):
    inputs, model_folder = Path(inputs), Path(model_folder)
    doc = store.read_fixed_manifest(inputs)
    inputs = inputs.resolve()
    if doc.get('schema') != INPUT_SCHEMA or set(doc) != INPUT_FIELDS:
        raise ValueError('observation input schema/fields differ; truth and policy are not inputs')
    store.refuse_publication_links(model_folder)
    model_folder = model_folder.resolve()
    manifest_path = model_folder / 'model_manifest.json'
    model_raw = manifest_path.read_bytes()
    if doc['model_manifest_sha256'] != _sha(model_raw):
        raise ValueError('model manifest hash differs')
    image_raw = safe_file(inputs, doc['image']).read_bytes()
    if len(image_raw) > BYTE_LIMIT or _sha(image_raw) != doc['image_sha256']:
        raise ValueError('image hash or size differs')
    bgr = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None or bgr.shape[0] * bgr.shape[1] > PIXEL_LIMIT:
        raise ValueError('invalid or oversized input image')
    manifest = load_manifest(manifest_path)
    if manifest.raw != json.loads(model_raw):
        raise ValueError('model manifest changed while loading')
    spec = manifest.input
    height = spec.crop[0] if spec.crop is not None else spec.height
    if height * spec.width > PIXEL_LIMIT:
        raise ValueError('oversized prediction grid')
    model = LaneSegModel.open(model_folder)
    if model.manifest.raw != manifest.raw:
        raise ValueError('model manifest changed while opening session')
    observed = observe_model_frame(model, bgr, _snapshot(doc['image_snapshot']),
        _snapshot(doc['anchor_snapshot']), doc['seed_pixels'], now_ns=doc['now_ns'], max_age_ns=max_age_ns)
    store.read_fixed_manifest(inputs)
    verify_files(model.manifest)
    if manifest_path.read_bytes() != model_raw:
        raise ValueError('model manifest changed during observation')
    return {'schema': SCHEMA, 'inputs': doc,
            'bindings': {'inputs_sha256': inputs.name, 'model_manifest_sha256': _sha(model_raw),
                         'image_sha256': doc['image_sha256'], 'max_age_ns': max_age_ns,
                         'classes': model.manifest.raw['output']['classes']}, 'observation': observed}


def _decode(raw):
    doc = json.loads(raw)
    if not isinstance(doc, dict) or set(doc) != {'schema', 'inputs', 'bindings', 'observation'} or doc['schema'] != SCHEMA:
        raise ValueError('observation artifact schema differs')
    observed = doc['observation']
    inputs, bindings = doc['inputs'], doc['bindings']
    if any(not isinstance(value, dict) for value in (observed, inputs, bindings)):
        raise ValueError('observation artifact mappings required')
    if inputs.get('schema') != INPUT_SCHEMA or set(inputs) != INPUT_FIELDS:
        raise ValueError('observation input schema/fields differ')
    if any(bindings[key] != inputs[key] for key in ('model_manifest_sha256', 'image_sha256')):
        raise ValueError('observation binding hashes differ')
    if any(not valid_digest(bindings.get(key)) for key in
           ('inputs_sha256', 'model_manifest_sha256', 'image_sha256')):
        raise ValueError('observation binding digests required')
    image, anchor = (_snapshot(inputs[key + '_snapshot']) for key in ('image', 'anchor'))
    errors = list(road_region_input_errors(image, anchor, now_ns=inputs['now_ns'], max_age_ns=bindings['max_age_ns']))
    if observed['input_errors'] != errors:
        raise ValueError('observation validity differs from snapshots and clock')
    if any(observed[key + '_snapshot_id'] != inputs[key + '_snapshot']['snapshot_id']
           for key in ('image', 'anchor')):
        raise ValueError('observation snapshot identity differs')
    if observed['input_errors'] and observed['current_region'] is not None:
        raise ValueError('invalid region inputs cannot carry a region')
    if observed['fitness_verdict'] != 'HOLD':
        raise ValueError('observation artifact must remain HOLD')
    check_revision(observed['model_revision'])
    profile = observed['camera_profile_revision']
    if not isinstance(profile, str) or not profile.strip() or profile != profile.strip():
        raise ValueError('camera profile revision required')
    preprocessing = observed['preprocessing']
    if not isinstance(preprocessing, dict):
        raise ValueError('observation preprocessing mapping required')
    spec = _parse_input(preprocessing['input'])
    source = preprocessing['source_shape']
    if (not isinstance(source, list) or len(source) != 2
            or any(type(v) is not int or v <= 0 for v in source) or math.prod(source) > PIXEL_LIMIT):
        raise ValueError('invalid source grid')
    height = spec.crop[0] if spec.crop is not None else spec.height
    lo, hi = spec.crop[2:] if spec.crop is not None else (0, height)
    if (height * spec.width > PIXEL_LIMIT or preprocessing['prediction_shape'] != [height, spec.width]
            or preprocessing['predicted_rows'] != [lo, hi]):
        raise ValueError('observation preprocessing grid or crop differs')
    seeds = inputs['seed_pixels']
    if (not isinstance(seeds, list) or any(not isinstance(p, list) or len(p) != 2
            or any(type(v) is not int for v in p) for p in seeds)):
        raise ValueError('anchors must be integer (row, col) pixels')
    mapped = [[int(np.floor((r + .5) * height / source[0])),
               int(np.floor((c + .5) * spec.width / source[1]))] for r, c in seeds]
    if preprocessing['seed_pixels'] != mapped:
        raise ValueError('observation anchor grid differs')
    classes = doc['bindings']['classes']
    road_masks(np.full((1, 1), 255, np.uint8), classes)
    labels = observed['labels']
    image_invalid = any(e in ('image_invalid', 'image_stale', 'image_future') for e in errors)
    if (labels is None) != image_invalid:
        raise ValueError('observation labels differ from image validity')
    if labels is None:
        if (observed['road_surface'] is not None or observed['current_region'] is not None
                or observed['region_reason'] != 'invalid_inputs' or observed['infer_latency_ms'] is not None):
            raise ValueError('abstained labels cannot carry masks')
        return doc
    latency = observed['infer_latency_ms']
    if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
        raise ValueError('inference latency must be finite and non-negative')
    labels = np.asarray(labels)
    if (labels.ndim != 2 or not labels.size or labels.size > PIXEL_LIMIT
            or not np.issubdtype(labels.dtype, np.integer)):
        raise ValueError('invalid labels grid')
    road, _ = road_masks(labels, classes)
    if list(labels.shape) != observed['preprocessing']['prediction_shape']:
        raise ValueError('labels/preprocessing grid differs')
    if np.any(labels[:lo] != 255) or np.any(labels[hi:] != 255):
        raise ValueError('labels outside model crop must remain unknown')
    for key in ('road_surface', 'current_region'):
        mask = observed[key]
        if mask is None:
            if key == 'road_surface':
                raise ValueError('labels require a road mask')
            continue
        mask = np.asarray(mask)
        if mask.shape != labels.shape or mask.dtype != np.bool_:
            raise ValueError('invalid binary mask shape/type')
        if key == 'road_surface' and not np.array_equal(mask, road):
            raise ValueError('road mask differs from class labels')
        if key == 'current_region' and np.any(mask & ~road):
            raise ValueError('region mask extends outside road')
    region, reason = (None, 'invalid_inputs') if errors else observed_road_region(labels, classes, mapped)
    actual = observed['current_region']
    if (observed['region_reason'] != reason or (actual is None) != (region is None)
            or (region is not None and not np.array_equal(actual, region))):
        raise ValueError('current region differs from observed anchors and road')
    return doc


def read_artifact(path, sha256):
    path = Path(path)
    store.refuse_publication_links(path)
    if path.stat().st_size > BYTE_LIMIT:
        raise ValueError('oversized observation artifact')
    raw = path.read_bytes()
    if len(raw) > BYTE_LIMIT or _sha(raw) != sha256:
        raise ValueError('observation artifact hash differs')
    return _decode(raw)


def execute(args):
    output = Path(args.out)
    try:
        if output.exists() or output.is_symlink():
            raise ValueError('output already exists')
        report = run(args.model, inputs=args.inputs, max_age_ns=args.max_age_ns)
        raw = (json.dumps(report, sort_keys=True, allow_nan=False,
                          default=lambda value: value.tolist()) + '\n').encode()
        if len(raw) > BYTE_LIMIT:
            raise ValueError('oversized observation artifact')
        _decode(raw)
        with output.open('xb') as stream:
            stream.write(raw)
        digest = _sha(raw)
        read_artifact(output, digest)
    except Exception as exc:
        # Backend-specific failures also close the diagnostic without an artifact.
        print(f'observation diagnostic error ({type(exc).__name__}): {exc}')
        return 2
    print(f'observation diagnostic HOLD: {output} sha256={digest}')
    return 0
