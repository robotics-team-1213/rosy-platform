"""D-682 immutable object replay; completed diagnostics always remain HOLD."""
from pathlib import Path
import json
import math

from road_fitness_replay import _identities, _snapshot
import class_sets
import intake
import review_evidence as review
import store
import cv2
import numpy as np
from control.sensing.perception.learned.detector import ObjectDetModel
from control.sensing.perception.learned.manifest import OBJECT_CLASSES, load_manifest, verify_files
from object_fitness import _fraction, evaluate_detections, evaluate_model_frame, summarize_frames


def _truth(folder):
    store.refuse_publication_links(Path(folder))
    folder = Path(folder).resolve()
    doc = store.read_fixed_manifest(folder)
    if (doc.get('schema') != 'rosy.perception.dataset/1' or doc.get('purpose') != 'eval'
            or doc.get('task') != 'object_det'):
        raise ValueError('fixed object evaluation dataset required')
    raw = review.safe_file(folder, 'object-classes.json').read_bytes()
    classes = json.loads(raw)
    names = tuple(c['name'] for c in classes['classes'])
    if (names != OBJECT_CLASSES or classes.get('task') != 'detect'
            or any(type(c.get('index')) is not int or c['index'] != i
                   for i, c in enumerate(classes['classes']))
            or class_sets._record(names, 'detect', classes['source'])['sha256'] != classes.get('sha256')
            or doc.get('classes') != classes['classes'] or doc.get('classes_sha256') != review.sha(raw)):
        raise ValueError('object class binding differs')
    authority = review.validate_authority(json.loads(review.safe_file(folder, 'authority.json').read_bytes()))
    if authority['decision_sha256'] != doc.get('authority_sha256'):
        raise ValueError('object review authority binding differs')
    approved, rows = _identities(authority['frames']), _identities(doc['frames'])
    if approved.keys() != rows.keys():
        raise ValueError('all reviewed frame identities required')
    images = {}
    for identity, frame in rows.items():
        row = approved[identity]
        if row['object_decision'] != 'approved' or row['frame_excluded'] or frame.get('split') != 'eval':
            raise ValueError('frame lacks approved complete object review')
        pairs = {'frame': 'frame', 'image_sha256': 'image_sha256', 'object_version': 'object_version',
                 'session': 'source_session', 'capture_group': 'capture_group'}
        if any(frame.get(k) != row[v] or type(frame.get(k)) is not type(row[v]) for k, v in pairs.items()):
            raise ValueError('object frame identity/hash/version differs')
        source, human = frame.get('source'), frame.get('review')
        if (not isinstance(source, dict) or not isinstance(human, dict)
                or review.sha(review.encoded(source)) != row['source_sha256']
                or review.sha(review.encoded(human)) != row['object_review_sha256']):
            raise ValueError('object source/review hash differs')
        if (human.get('review_status') != 'approved' or human.get('complete_frame_review') is not True
                or not isinstance(human.get('boxes'), list)
                or human.get('index') != frame['frame'] or type(human.get('index')) is not int
                or human.get('image_sha256') != frame['image_sha256']):
            raise ValueError('explicit complete object review required')
        if (source.get('source_kind') != 'mcap' or source.get('fixed_eval_overlap') is not True
                or any(not isinstance(frame.get(k), str) or not frame[k] for k in ('session', 'capture_group'))
                or any(source.get(k) != row[v] or type(source.get(k)) is not type(row[v])
                       for k, v in {'index': 'frame', 'image_sha256': 'image_sha256', 'width': 'width',
                                    'height': 'height', 'source_session': 'source_session',
                                    'capture_group': 'capture_group'}.items())):
            raise ValueError('reserved MCAP source binding differs')
        try:
            source_identity = review.identity(source)
        except (KeyError, TypeError, StopIteration) as exc:
            raise ValueError('invalid MCAP source identity') from exc
        if source_identity != identity:
            raise ValueError('MCAP source identity differs')
        image_raw = review.safe_file(folder, frame['image']).read_bytes()
        image = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
        if (review.sha(image_raw) != frame['image_sha256'] or image is None
                or image.shape[:2] != (row['height'], row['width'])):
            raise ValueError('approved image hash or dimensions differ')
        images[identity] = image
    return folder, doc, rows, images


def run(model_folder, *, store_root, eval_dir, inputs, max_age_ns):
    if type(max_age_ns) is not int or max_age_ns <= 0:
        raise ValueError('max_age_ns must be a positive integer')
    for path in (model_folder, inputs):
        store.refuse_publication_links(Path(path))
    model_folder, inputs = Path(model_folder).resolve(), Path(inputs).resolve()
    model_path = model_folder / 'model_manifest.json'
    model_raw = model_path.read_bytes()
    manifest = load_manifest(model_folder)
    verify_files(manifest)
    if manifest.task != 'object_det':
        raise ValueError('object detector required')
    truth_folder, truth_doc, frames, images = _truth(eval_dir)
    observations = store.read_fixed_manifest(inputs)
    expected = dict(model_revision=manifest.model_revision, model_manifest_sha256=review.sha(model_raw),
                    eval_sha256=truth_folder.name,
                    preprocessing_sha256=review.sha(review.encoded(manifest.raw['input'])))
    if (observations.get('schema') != 'rosy.perception.object-inputs/1'
            or any(observations.get(k) != v for k, v in expected.items())):
        raise ValueError('fixed model/evaluation/preprocessing input binding differs')
    conf = observations.get('detector_confidence')
    iou = observations.get('detector_nms_iou')
    if (type(conf) not in (int, float) or not math.isfinite(conf) or not 0 <= conf <= 1
            or not _fraction(iou) or not _fraction(observations.get('match_iou'))
            or not _fraction(observations.get('small_area_fraction'))):
        raise ValueError('fixed detector/metric fractions required')
    metric = {k: observations[k] for k in ('match_iou', 'small_area_fraction')}
    observed = _identities(observations.get('frames'))
    if observed.keys() != frames.keys():
        raise ValueError('observed/evaluation frame identities differ')
    refs = observations.get('training_refs')
    if not isinstance(refs, list) or not refs or any(not isinstance(r, str) for r in refs) or len(set(refs)) != len(refs):
        raise ValueError('fixed training refs required')
    registry = store.Store(store_root)
    training, sessions, groups, hashes = [], set(), set(), set()
    for ref in refs:
        name, digest = store.parse_dataset_ref(ref)
        path = registry.dataset_path(name, digest)
        doc = intake._verified_manifest(path)
        if doc.get('purpose') != 'train' or not isinstance(doc.get('frames'), list) or not doc['frames']:
            raise ValueError('non-empty fixed training dataset required')
        if digest == manifest.raw['dataset']['revision']:
            if (len(doc['classes']) != len(OBJECT_CLASSES)
                    or any(type(c.get('index')) is not int or c['index'] != i
                           or c['name'] != OBJECT_CLASSES[i] or c['role'] != 'object'
                           for i, c in enumerate(doc['classes']))):
                raise ValueError('candidate training class order or role differs')
        for frame in doc['frames']:
            if not all(isinstance(frame.get(k), str) and frame[k] for k in ('session', 'capture_group')):
                raise ValueError('training source group is unverified')
            sessions.add(frame['session'])
            groups.add(frame['capture_group'])
            actual = review.sha(review.safe_file(path.resolve(), frame['image']).read_bytes())
            if actual != frame.get('image_sha256'):
                raise ValueError('training image hash differs')
            hashes.add(actual)
        training.append(path)
    if manifest.raw['dataset']['revision'] not in {p.name for p in training}:
        raise ValueError('candidate training dataset is absent from fixed refs')
    reservations = registry.eval_reservations()
    snapshots = {}
    for identity, frame in frames.items():
        supplied = observed[identity]
        if supplied.get('image_sha256') != frame['image_sha256']:
            raise ValueError('observed image hash differs')
        if reservations.get(frame['session']) != frame['capture_group']:
            raise ValueError('evaluation source reservation differs')
        if frame['session'] in sessions or frame['capture_group'] in groups or frame['image_sha256'] in hashes:
            raise ValueError('training/evaluation source or image overlap')
        image = images[identity]
        evaluate_detections(None, frame['review']['boxes'], frame_size=(image.shape[1], image.shape[0]),
                            domain=supplied.get('domain'), conditions=supplied.get('conditions'), **metric)
        snapshots[identity] = _snapshot(supplied.get('image_snapshot'))
    model = ObjectDetModel.open(model_folder, conf=conf, iou=iou)
    if model.manifest.raw != manifest.raw or model_path.read_bytes() != model_raw:
        raise ValueError('model manifest changed while loading')
    reports = []
    for identity, supplied in observed.items():
        report = evaluate_model_frame(model, images[identity], snapshots[identity], frames[identity]['review']['boxes'],
            now_ns=supplied.get('now_ns'), max_age_ns=max_age_ns, domain=supplied['domain'],
            conditions=supplied['conditions'], **metric)
        reports.append(dict(identity=identity, **report))
    for path in (truth_folder, inputs, *training):
        store.read_fixed_manifest(path)
    verify_files(model.manifest)
    if model_path.read_bytes() != model_raw or registry.eval_reservations() != reservations:
        raise ValueError('model manifest or evaluation reservations changed during replay')
    return dict(fitness_verdict='HOLD', hold_reasons=['live_review_freshness_unverified',
        'reviewer_independence_unverified', 'upstream_training_closure_unverified',
        'occlusion_review_independence_unverified', 'acceptance_profile_and_device_evidence_missing'],
        bindings=dict(expected, inputs_sha256=inputs.name, training_refs=refs,
                      authority_sha256=truth_doc['authority_sha256'], declared_training_disjoint=True,
                      max_age_ns=max_age_ns), frames=reports, summary=summarize_frames(reports))


def execute(args):
    output = Path(args.out)
    try:
        if output.exists() or output.is_symlink():
            raise ValueError('output already exists')
        report = run(args.model, store_root=args.store, eval_dir=args.eval, inputs=args.inputs, max_age_ns=args.max_age_ns)
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n'
        with output.open('x', encoding='utf-8') as stream:
            stream.write(raw)
    except Exception as exc:
        # Backend-specific failures also close the diagnostic without a report.
        print(f'object fitness diagnostic error ({type(exc).__name__}): {exc}')
        return 2
    print(f'object fitness diagnostic HOLD: {output}')
    return 0
