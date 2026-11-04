"""Registered native input summaries; no paths, automatic associations or human labels."""
from pathlib import Path
from copy import deepcopy

import omx_web
import native_segments


def list_inputs(workspace, center, bindings):
    if workspace is None:
        return bind_summaries([], bindings)
    result = []
    for row in workspace.list():
        if row['kind'] != 'omx':
            continue
        current = omx_web.prepared_set(row, workspace, center)
        if current is None:
            continue
        current['prepared_id'] = row['id']
        revision = current.get('source_revision')
        current['available'] = bool(revision and not current.get('error'))
        current['segments_trainable'] = {'ok': False, 'reason': '저장한 독립 학습·평가 구간이 필요합니다.'}
        saved = current.get('segment_review') or {}
        if current['available'] and saved.get('version', 0) > 0 and saved.get('document'):
            try:
                report = omx_web._read(Path(row['path']), 'inspection.json')
                native_segments.validate_selection(report, saved['document'])
                current['segments_trainable'] = {'ok': not current.get('fixture_only', False)}
            except (KeyError, TypeError, ValueError, OSError) as exc:
                current['segments_trainable'] = {'ok': False, 'reason': str(exc)}
        result.append(current)
    return bind_summaries(result, bindings)


def bind_summaries(rows, bindings):
    """Refresh associations cheaply; cached integrity is never used for job admission."""
    result = deepcopy(rows)
    for row in result:
        row['binding'] = next((binding for binding in bindings if binding['prepared_id'] == row['prepared_id']), None)
        if row['binding'] and row['binding'].get('source_revision') != row.get('source_revision'):
            row['available'] = False
            row['error'] = '연결한 원본 revision이 바뀌었습니다. 원본과 과제 연결을 다시 확인하세요.'
    present = {row['prepared_id'] for row in result}
    for binding in bindings:
        if binding['prepared_id'] not in present:
            result.append(dict(prepared_id=binding['prepared_id'], id=binding['prepared_id'],
                name='연결한 시연 · 원본 확인 필요', source_revision=binding['source_revision'],
                available=False, binding=binding, fixture_only=False,
                error='연결한 시연을 현재 자료 목록에서 찾을 수 없습니다. 원본을 확인하세요.',
                latest_review_id=None, trainable={'ok': False}, segment_review={'version': 0, 'document': None}))
    return result
