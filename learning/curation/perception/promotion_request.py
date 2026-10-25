"""Learning 승격 요청 묶음(D-874): 확정 정답 평가 근거를 봉인해 넘길 뿐, 승인·배포는 Fleet(D-793)."""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'learning/registry/perception'))
import review_evidence  # noqa: E402
from store import Store, _sha256, parse_dataset_ref, read_fixed_manifest  # noqa: E402

SCHEMA = 'rosy.learning.promotion-request/1'
HUMAN = ['human_reviewed_eval']  # review_eval_bootstrap.py; build.py eval sets carry lidar/trajectory (D-449)
# Approval, stage and authority belong to Fleet's record; Learning cannot even spell them (D-793).
FORBIDDEN = re.compile(r'approv|stage|authori|decision|promot|activat|deploy|grant', re.I)
_SHA = re.compile(r'[0-9a-f]{64}')


def _json(path, missing):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(missing)
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict):
        raise ValueError(missing)
    return doc


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


def _training(root, revision):
    """Commit and runtime recorded by learning_cycle.py for this model, or None when not recorded."""
    try:
        state = _json(Path(root) / 'state.json', '')
    except (OSError, ValueError):
        return None
    rows = [row for row in (state.get('cycles') or {}).values()
            if isinstance(row, dict) and isinstance(row.get('result'), dict)
            and row['result'].get('revision') == revision and isinstance(row.get('provenance'), dict)]
    return rows[-1]['provenance'] if rows else None


def build(root, requester, now=None):
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
        if (not isinstance(item, dict) or not _SHA.fullmatch(str(item.get('sha256')))
                or Path(str(item.get('name'))).name != item.get('name')
                or not (root / item['name']).is_file() or _sha256(root / item['name']) != item['sha256']):
            raise ValueError('모델 파일 해시가 수용 보고와 다릅니다.')
    ev = report.get('eval')
    if not isinstance(ev, dict) or not isinstance(ev.get('set'), dict):
        raise ValueError('평가 결과가 없습니다. 사람이 확정한 평가셋으로 수용 평가를 돌려야 합니다(D-857 §4).')
    if ev.get('disjoint') is not True:
        raise ValueError('학습 데이터와 평가셋이 분리되었는지 확인되지 않았습니다.')
    digest, eval_dir = ev['set'].get('content_sha'), Path(str(ev['set'].get('path')))
    groups = ev.get('source_groups')
    if not isinstance(groups, list) or not groups:
        raise ValueError('평가 보고에 채점한 사진의 정답 출처가 없습니다.')
    _human_only(groups)
    try:
        if eval_dir.name != digest:
            raise ValueError
        doc = read_fixed_manifest(eval_dir)
    except (OSError, ValueError):
        raise ValueError('평가셋을 이 작업대에서 확인할 수 없거나 내용 해시가 다릅니다.') from None
    if doc.get('purpose') != 'eval' or not doc.get('frames'):
        raise ValueError('평가셋이 아닙니다.')
    _human_only(doc['frames'])
    try:
        name, dataset = parse_dataset_ref(str(ev.get('training_dataset')))
        if dataset != (manifest.get('dataset') or {}).get('revision'):
            raise ValueError
        data = read_fixed_manifest(Store(eval_dir.parents[2]).dataset_path(name, dataset))
    except (OSError, ValueError, IndexError):
        raise ValueError('학습 데이터셋을 확인할 수 없거나 모델 manifest의 revision과 다릅니다.') from None
    share = data.get('external_sources') or {'huggingface_frames': 0, 'split': 'train_only'}
    if share.get('split') != 'train_only':
        raise ValueError('HF 사진이 학습 전용으로 묶이지 않았습니다(D-857).')
    bundle = {'schema': SCHEMA, 'state': 'requested', 'requester': str(requester),
              'created_at': now or dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
              'model': {'revision': revision, 'files': [{'name': f['name'], 'sha256': f['sha256']} for f in files]},
              'dataset': {'name': name, 'revision': dataset, 'external_sources': share},
              'evaluation': {'set': eval_dir.parent.name, 'content_sha': digest, 'sources': HUMAN,
                             'frames': ev.get('frames'), 'miou': ev.get('miou'),
                             'iou': [{'class': k, 'value': v} for k, v in sorted((ev.get('iou') or {}).items())]},
              'training': _training(root, revision)}
    validate(bundle)
    return bundle


def validate(bundle):
    if bundle.get('schema') != SCHEMA or bundle.get('state') != 'requested':
        raise ValueError('Learning은 requested 상태의 승격 요청만 만듭니다(D-793).')
    if (bundle.get('evaluation') or {}).get('sources') != HUMAN:
        raise ValueError('확정 정답 평가가 아닌 승격 요청입니다(D-857 §4).')

    def walk(value):
        for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
            if isinstance(key, str) and FORBIDDEN.search(key):
                raise ValueError(f'Learning은 승인·단계·권한 필드({key})를 쓸 수 없습니다(D-793).')
            if isinstance(item, (dict, list)):
                walk(item)
    walk(bundle)


def write(state, bundle):
    """Write once at <state>/promotion-requests/<sha>.json; the same bytes again return the same sha."""
    validate(bundle)
    raw = review_evidence.encoded(bundle)
    digest = review_evidence.sha(raw)
    folder = Path(state) / 'promotion-requests'
    folder.mkdir(exist_ok=True)
    path, temporary = folder / f'{digest}.json', folder / f'.{digest}.{os.getpid()}.tmp'
    temporary.write_bytes(raw)
    try:
        os.link(temporary, path)  # create-only and atomic: a half-written file never takes the name
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('같은 해시 이름에 다른 내용이 있습니다. 요청 기록을 확인하세요.') from None
    finally:
        temporary.unlink()
    return {'sha256': digest, 'model_revision': bundle['model']['revision']}


def listing(state, items):
    """Read-only: each perception candidate with its refusal reason, and the sealed requests so far."""
    candidates = []
    for item in items:
        if item['kind'] != 'perception':
            continue
        # shortcut: re-hashes the eval set and dataset on every read; cache by mtime if the page gets slow.
        try:
            row = {'qualified': True, 'model_revision': build(item['path'], '')['model']['revision']}
        except (OSError, ValueError, KeyError, TypeError) as exc:
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
