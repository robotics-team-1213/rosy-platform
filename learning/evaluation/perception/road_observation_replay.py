"""D-673 truth-free file diagnostics; no device delivery, admission or commands."""
from pathlib import Path
import hashlib
import json

from road_fitness_replay import _snapshot
import cv2
import numpy as np
import store
from control.sensing.perception.learned.manifest import verify_files
from control.sensing.perception.learned.runner import LaneSegModel
from control.sensing.perception.learned.road_observation import observe_model_frame
from control.sensing.perception.learned.road_region import road_masks

INPUT_SCHEMA = 'rosy.perception.road-observation-input/1'
SCHEMA = 'rosy.perception.road-observation-artifact/1'
INPUT_FIELDS = {'schema', 'model_manifest_sha256', 'image', 'image_sha256',
                'image_snapshot', 'anchor_snapshot', 'seed_pixels', 'now_ns'}
PIXEL_LIMIT = 1_000_000
BYTE_LIMIT = 64 * 1024 * 1024


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(model_folder, *, inputs, max_age_ns):
    inputs, model_folder = Path(inputs).resolve(), Path(model_folder)
    doc = store.read_fixed_manifest(inputs)
    if doc.get('schema') != INPUT_SCHEMA or set(doc) != INPUT_FIELDS:
        raise ValueError('observation input schema/fields differ; truth and policy are not inputs')
    store.refuse_publication_links(model_folder)
    model_folder = model_folder.resolve()
    manifest_path = model_folder / 'model_manifest.json'
    model_raw = manifest_path.read_bytes()
    if doc['model_manifest_sha256'] != _sha(model_raw):
        raise ValueError('model manifest hash differs')
    relative = Path(doc['image'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('image must be inside fixed inputs')
    image_raw = (inputs / relative).read_bytes()
    if len(image_raw) > BYTE_LIMIT or _sha(image_raw) != doc['image_sha256']:
        raise ValueError('image hash or size differs')
    bgr = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None or bgr.shape[0] * bgr.shape[1] > PIXEL_LIMIT:
        raise ValueError('invalid or oversized input image')
    model = LaneSegModel.open(model_folder)
    if model.manifest.raw != json.loads(model_raw):
        raise ValueError('model manifest changed while loading')
    spec = model.manifest.input
    height = spec.crop[0] if spec.crop is not None else spec.height
    if height * spec.width > PIXEL_LIMIT:
        raise ValueError('oversized prediction grid')
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
    if observed['fitness_verdict'] != 'HOLD':
        raise ValueError('observation artifact must remain HOLD')
    classes = doc['bindings']['classes']
    road_masks(np.full((1, 1), 255, np.uint8), classes)
    labels = observed['labels']
    if labels is None:
        if observed['road_surface'] is not None or observed['current_region'] is not None:
            raise ValueError('abstained labels cannot carry masks')
        return doc
    labels = np.asarray(labels)
    if (labels.ndim != 2 or not labels.size or labels.size > PIXEL_LIMIT
            or not np.issubdtype(labels.dtype, np.integer)):
        raise ValueError('invalid labels grid')
    road, _ = road_masks(labels, classes)
    if list(labels.shape) != observed['preprocessing']['prediction_shape']:
        raise ValueError('labels/preprocessing grid differs')
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
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'observation diagnostic error: {exc}')
        return 2
    print(f'observation diagnostic HOLD: {output} sha256={digest}')
    return 0
