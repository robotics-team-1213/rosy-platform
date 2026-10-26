"""D-874 promotion request bundle: the shape Learning seals and Fleet re-checks before a human decides (D-793).

`encoded` is the one byte form of a bundle: non-ASCII kept, sorted keys, a trailing newline. It is
Learning's review evidence encoding, not `fleet_export.encoded`. Validation proves shape only; it
never approves, stages or deploys anything.
"""
import json
import math
import re

SCHEMA = 'rosy.learning.promotion-request/1'
HUMAN = ['human_reviewed_eval']
# Approval, stage and authority belong to Fleet's record; Learning cannot even spell them (D-793).
FORBIDDEN = re.compile(r'approv|stage|authori|decision|promot|activat|deploy|grant', re.I)
SHARE = {'huggingface_frames', 'percent', 'groups', 'split', 'own_forced_train'}
_SHA = re.compile(r'[0-9a-f]{64}')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


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
