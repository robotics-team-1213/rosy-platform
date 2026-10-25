"""Learning 승격 요청 묶음(D-874): 확정 정답 평가 근거를 봉인해 넘길 뿐, 승인·배포는 Fleet(D-793)."""
import datetime as dt
import json
import math
import os
import re
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'learning/registry/perception'))
import review_evidence  # noqa: E402
from store import Store, _sha256, content_sha, parse_dataset_ref, read_fixed_manifest  # noqa: E402

SCHEMA = 'rosy.learning.promotion-request/1'
HUMAN = ['human_reviewed_eval']
BOOTSTRAP = 'review_eval_bootstrap.py --publish (D-475)'  # the only writer of approved human eval sets
# Approval, stage and authority belong to Fleet's record; Learning cannot even spell them (D-793).
FORBIDDEN = re.compile(r'approv|stage|authori|decision|promot|activat|deploy|grant', re.I)
SHARE = {'huggingface_frames', 'percent', 'groups', 'split', 'own_forced_train'}
NO_SHARE = {'huggingface_frames': 0, 'percent': 0.0, 'groups': [], 'split': 'train_only', 'own_forced_train': 0}
_SHA = re.compile(r'[0-9a-f]{64}')
_LOCK = threading.Lock()
_CACHE = {}


def _json(path, missing, limit=2 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(missing)
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict):
        raise ValueError(missing)
    return doc


def _cached(paths, compute, fresh):
    """POST hashes again; GET reuses a digest while every path keeps its size and mtime_ns."""
    key = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    if fresh or key not in _CACHE:
        if len(_CACHE) > 512:
            _CACHE.clear()
        _CACHE[key] = compute()
    return _CACHE[key]


def _fixed(folder, fresh):
    if fresh:
        return read_fixed_manifest(folder)
    # shortcut: GET still stats every file of the folder; an index per content_sha would remove that.
    files = sorted(p for p in folder.rglob('*') if p.is_file())
    if not files or _cached([folder, *files], lambda: content_sha(folder), False) != folder.name:
        raise ValueError('content hash differs')
    return _json(folder / 'manifest.json', 'manifest missing', 64 * 1024 * 1024)


def _human_only(frames):
    hf = sum(f.get('source_kind') == 'huggingface' or str(f.get('session', '')).startswith('hf:') for f in frames)
    auto = sum(bool({'lidar', 'trajectory'} & set(f.get('sources') or [])) for f in frames)
    other = sum(f.get('sources') != HUMAN for f in frames)
    if hf:
        raise ValueError(f'평가셋에 HF 사진 {hf}장이 있습니다. HF 사진은 학습에만 씁니다(D-857).')
    if auto:
        raise ValueError(f'평가셋에 자동 라벨(LiDAR·궤적) 사진 {auto}장이 있습니다. '
                         '자동 라벨은 사람이 확정한 정답이 아닙니다(D-449, D-857 §4).')
    if other:
        raise ValueError(f'사람 확정 정답 표시가 없는 평가 사진이 {other}장 있습니다(D-857 §4).')


def anchor(control):
    """The owned learning cycle bound to this workspace: its dataset store and its state ledger."""
    if control is None:
        raise ValueError('이 작업대에 소유 학습 실행기가 연결되지 않아 평가 근거의 출처를 확인할 수 없습니다.')
    store = json.loads(Path(control.config).read_bytes())['cycle']['trainer']['store']
    return Path(store).resolve(), Path(control.out) / 'state.json'


def build(root, requester, control, *, fresh=True, now=None):
    """The request bundle for one registered result directory; ValueError carries the Korean refusal."""
    root = Path(root)
    report = _json(root / 'intake_report.json', '모델 수용 보고(intake_report.json)가 없습니다.')
    if report.get('verdict') != 'pass':
        raise ValueError('모델 수용 검사를 통과한 후보가 아닙니다.')
    manifest = _json(root / 'model_manifest.json', '모델 manifest가 없습니다.')
    revision, files = report.get('model_revision'), report.get('files')
    if manifest.get('model_revision') != revision or not isinstance(files, list) or not files:
        raise ValueError('수용 보고와 모델 manifest가 다른 모델입니다.')
    for item in files:
        file = root / str(item.get('name')) if isinstance(item, dict) else root
        if (not isinstance(item, dict) or Path(str(item.get('name'))).name != item.get('name') or not file.is_file()
                or _cached([file], lambda: _sha256(file), fresh) != item.get('sha256')):
            raise ValueError('모델 파일 해시가 수용 보고와 다릅니다.')
    ev = report.get('eval')
    if not isinstance(ev, dict) or not isinstance(ev.get('set'), dict):
        raise ValueError('평가 결과가 없습니다. 사람이 확정한 평가셋으로 수용 평가를 돌려야 합니다(D-857 §4).')
    if ev.get('disjoint') is not True:
        raise ValueError('학습 데이터와 평가셋이 분리되었는지 확인되지 않았습니다.')
    groups = ev.get('source_groups')
    if not isinstance(groups, list) or not groups or not all(isinstance(g, dict) for g in groups):
        raise ValueError('평가 보고에 채점한 사진의 정답 출처가 없습니다.')
    _human_only(groups)
    store, ledger = anchor(control)
    digest, eval_dir = ev['set'].get('content_sha'), Path(str(ev['set'].get('path'))).resolve()
    if not eval_dir.is_relative_to(store / 'evalsets') or len(eval_dir.relative_to(store / 'evalsets').parts) != 2:
        raise ValueError('평가셋이 이 작업대의 데이터셋 저장소 밖에 있습니다.')
    try:
        if eval_dir.name != digest:
            raise ValueError
        doc = _fixed(eval_dir, fresh)
    except (OSError, ValueError):
        raise ValueError('평가셋을 이 작업대에서 확인할 수 없거나 내용 해시가 다릅니다.') from None
    frames = doc.get('frames')
    if doc.get('purpose') != 'eval' or not isinstance(frames, list) or not frames or not all(isinstance(f, dict) for f in frames):
        raise ValueError('평가셋이 아닙니다.')
    _human_only(frames)
    if doc.get('builder') != BOOTSTRAP or not all(_SHA.fullmatch(str(f.get('approval_sha256'))) for f in frames):
        raise ValueError('사람 검수 승인으로 공개한 평가셋(review_eval_bootstrap)이 아닙니다(D-475).')
    cycles = _json(ledger, '이 작업대의 학습 기록(learning_cycle)을 읽을 수 없습니다.', 16 * 1024 * 1024).get('cycles')
    sealed = [{'name': f['name'], 'sha256': f['sha256']} for f in files]
    # The revision string is the requester's own; the row must have published this very folder and these bytes.
    rows = [row for row in (cycles.values() if isinstance(cycles, dict) else [])
            if isinstance(row, dict) and row.get('status') == 'ready' and isinstance(row.get('result'), dict)
            and row['result'].get('revision') == revision and isinstance(row['result'].get('location'), str)
            and Path(row['result']['location']).resolve() == root.resolve() and row.get('files') == sealed]
    if not rows:
        raise ValueError('이 결과 폴더와 모델 파일을 만든 학습 기록(learning_cycle)이 이 작업대에 없습니다.')
    if rows[-1].get('eval_set') != digest:
        raise ValueError('학습 기록의 평가셋 해시와 수용 보고의 평가셋이 다릅니다.')
    try:
        name, dataset = parse_dataset_ref(str(ev.get('training_dataset')))
        if dataset != (manifest.get('dataset') or {}).get('revision'):
            raise ValueError
        data = _fixed(Store(store).dataset_path(name, dataset), fresh)
    except (OSError, ValueError):
        raise ValueError('학습 데이터셋을 확인할 수 없거나 모델 manifest의 revision과 다릅니다.') from None
    iou = ev.get('iou')
    provenance = rows[-1].get('provenance')
    bundle = {'schema': SCHEMA, 'state': 'requested', 'requester': requester,
              'created_at': now or dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
              'model': {'revision': revision, 'files': sealed},
              'dataset': {'name': name, 'revision': dataset,
                          'external_sources': data.get('external_sources', NO_SHARE)},
              'evaluation': {'set': eval_dir.parent.name, 'content_sha': digest, 'sources': HUMAN,
                             'frames': ev.get('frames'), 'miou': ev.get('miou'),
                             'iou': [{'class': k, 'value': v} for k, v in sorted(iou.items())]
                             if isinstance(iou, dict) else iou},
              'training': None if provenance is None else {
                  'commit': provenance.get('source_commit'), 'python': provenance.get('python'),
                  'torch': provenance.get('torch')} if isinstance(provenance, dict) else provenance}
    validate(bundle)
    return bundle


def _fields(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f'승격 요청의 {where} 필드가 정해진 목록과 다릅니다.')


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _count(value):
    return type(value) is int and value >= 0


def validate(bundle):
    """A true allowlist: every key and value type of the sealed bundle is fixed here."""
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA or bundle.get('state') != 'requested':
        raise ValueError('Learning은 requested 상태의 승격 요청만 만듭니다(D-793).')

    def walk(value):
        for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
            if isinstance(key, str) and FORBIDDEN.search(key):
                raise ValueError(f'Learning은 승인·단계·권한 필드({key})를 쓸 수 없습니다(D-793).')
            if isinstance(item, (dict, list)):
                walk(item)
    walk(bundle)
    _fields(bundle, {'schema', 'state', 'requester', 'created_at', 'model', 'dataset', 'evaluation', 'training'}, '최상위')
    model, data, ev, training = bundle['model'], bundle['dataset'], bundle['evaluation'], bundle['training']
    _fields(model, {'revision', 'files'}, 'model')
    _fields(data, {'name', 'revision', 'external_sources'}, 'dataset')
    _fields(data['external_sources'], SHARE, 'external_sources')
    _fields(ev, {'set', 'content_sha', 'sources', 'frames', 'miou', 'iou'}, 'evaluation')
    share = data['external_sources']
    checks = [_text(bundle['requester'], 128), _text(bundle['created_at'], 40), _text(model['revision'], 128),
              isinstance(model['files'], list) and bool(model['files']),
              _text(data['name'], 128), _SHA.fullmatch(str(data['revision'])) is not None,
              _count(share['huggingface_frames']), _number(share['percent']), _count(share['own_forced_train']),
              isinstance(share['groups'], list) and all(_text(g, 256) for g in share['groups']),
              share['split'] == 'train_only', _text(ev['set'], 128), _SHA.fullmatch(str(ev['content_sha'])) is not None,
              ev['sources'] == HUMAN, type(ev['frames']) is int and ev['frames'] > 0, _number(ev['miou']),
              isinstance(ev['iou'], list)]
    if not all(checks):
        raise ValueError('승격 요청 값의 형식이 맞지 않습니다(유한한 숫자·정수 장수·학습 전용 HF·확정 정답 출처).')
    for item in model['files']:
        _fields(item, {'name', 'sha256'}, 'model.files')
        if not _text(item['name'], 255) or not _SHA.fullmatch(str(item['sha256'])):
            raise ValueError('모델 파일 이름 또는 sha256 형식이 맞지 않습니다.')
    for item in ev['iou']:
        _fields(item, {'class', 'value'}, 'evaluation.iou')
        if not _text(item['class'], 128) or not _number(item['value']):
            raise ValueError('클래스별 IoU는 유한한 숫자여야 합니다.')
    if training is not None:
        _fields(training, {'commit', 'python', 'torch'}, 'training')
        if (not (training['commit'] is None or re.fullmatch(r'[0-9a-f]{40}', str(training['commit'])))
                or not _text(training['python'], 32) or not (training['torch'] is None or _text(training['torch'], 32))):
            raise ValueError('학습 commit·Python·torch 기록 형식이 맞지 않습니다.')


def write(state, bundle):
    """Write once at <state>/promotion-requests/<sha>.json; the same model request again returns the first one."""
    validate(bundle)
    raw = review_evidence.encoded(bundle)
    digest = review_evidence.sha(raw)
    folder = Path(state) / 'promotion-requests'
    folder.mkdir(exist_ok=True)
    same = {key: value for key, value in bundle.items() if key != 'created_at'}
    with _LOCK:  # one server process; the lock makes the duplicate check and the create one step
        for path in sorted(folder.glob('*.json')):
            existing = path.read_bytes()
            if (review_evidence.sha(existing) == path.stem
                    and {k: v for k, v in json.loads(existing).items() if k != 'created_at'} == same):
                return {'sha256': path.stem, 'model_revision': bundle['model']['revision']}
        path, temporary = folder / f'{digest}.json', folder / f'.{digest}.{uuid.uuid4().hex}.tmp'
        temporary.write_bytes(raw)
        try:
            os.link(temporary, path)  # create-only and atomic: a half-written file never takes the name
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError('같은 해시 이름에 다른 내용이 있습니다. 요청 기록을 확인하세요.') from None
        finally:
            temporary.unlink()
    return {'sha256': digest, 'model_revision': bundle['model']['revision']}


def listing(state, items, control):
    """Read-only and cheap: each perception candidate with its refusal reason, and the sealed requests so far."""
    candidates = []
    for item in items:
        if item['kind'] != 'perception':
            continue
        try:
            row = {'qualified': True,
                   'model_revision': build(item['path'], 'listing', control, fresh=False)['model']['revision']}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            row = {'qualified': False, 'reason': str(exc)}
        candidates.append(dict(row, id=item['id'], name=item['name']))
    requests = []
    for path in sorted((Path(state) / 'promotion-requests').glob('*.json')):
        raw = path.read_bytes()
        if review_evidence.sha(raw) == path.stem:
            doc = json.loads(raw)
            requests.append({'sha256': path.stem, 'model_revision': doc['model']['revision'],
                             'requester': doc['requester'], 'created_at': doc['created_at']})
    return {'candidates': candidates, 'requests': requests}
