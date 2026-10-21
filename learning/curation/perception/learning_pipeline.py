"""Read-only current-review progress from the bound owner's ledger, never admission."""
import re


def snapshot(ledger):
    """Return bounded public evidence for selected cycles, excluding private config."""
    if not isinstance(ledger, dict):
        raise ValueError('학습 실행 기록은 객체여야 합니다.')
    pipeline, cycles = ledger.get('review_autobuild', {}), ledger.get('cycles', {})
    if not isinstance(pipeline, dict) or not isinstance(cycles, dict):
        raise ValueError('학습 단계 기록을 읽을 수 없습니다.')
    keys = pipeline.get('cycle_keys', [])
    if (not isinstance(keys, list) or len(keys) > 1000
            or not all(isinstance(key, str) and 0 < len(key) <= 128 for key in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError('현재 학습 시도 목록을 확인하세요.')
    authority = pipeline.get('authority')
    if authority is not None:
        if (not isinstance(authority, dict)
                or not re.fullmatch(r'[0-9a-f]{32}', str(authority.get('workspace_id', '')))
                or type(authority.get('generation')) is not int or authority['generation'] < 0
                or not re.fullmatch(r'[0-9a-f]{64}', str(authority.get('decision_sha256', '')))):
            raise ValueError('검수 결정 출처를 확인하세요.')
        authority = {key: authority[key] for key in ('workspace_id', 'generation', 'decision_sha256')}
    dataset = pipeline.get('dataset')
    referenced = [cycles.get(key, {}) for key in keys]
    if any(not isinstance(row, dict) or not isinstance(row.get('result', {}), dict) for row in referenced):
        raise ValueError('현재 학습 시도 기록을 읽을 수 없습니다.')
    # Completed owner iterations keep the dataset on the selected cycles only.
    if dataset is None and referenced and all(row.get('dataset') == referenced[0].get('dataset') for row in referenced):
        dataset = referenced[0].get('dataset')
    if dataset is not None and (not isinstance(dataset, str) or len(dataset) > 200
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*@[0-9a-f]{64}', dataset)):
        raise ValueError('데이터셋 버전을 확인하세요.')
    selected = []
    for row in referenced:
        revision = row.get('result', {}).get('revision')
        selected.append(dict(status=str(row.get('status', 'pending'))[:100],
            dataset=row.get('dataset') if row.get('dataset') == dataset else None,
            revision=revision if isinstance(revision, str) and 0 < len(revision) <= 200 else None,
            error=str(row.get('error', ''))[:500]))
    blockers = pipeline.get('blockers', [])
    return dict(status=str(pipeline.get('status', 'waiting'))[:100], authority=authority,
        dataset=dataset, cycles=selected,
        blockers=[reason[:500] for reason in blockers[:20] if isinstance(reason, str)]
        if isinstance(blockers, list) else [])


def project(current, *, counts, pixel_counts, preparation, control):
    """Tie stages to one current decision identity; incomplete evidence stays waiting."""
    stages = [dict(id=key, label=label, state='waiting', detail='앞 단계가 끝나면 확인합니다.')
              for key, label in [('data', '자료 선택'), ('review', '픽셀 검수'),
                  ('preparation', '승인 자료 준비'), ('dataset', '데이터셋 생성'),
                  ('training', '학습'), ('evaluation', '평가'), ('application', '적용 검토')]]
    result = dict(identity={key: current[key] for key in
                  ('workspace_id', 'generation', 'decision_sha256')}, stages=stages,
                  current=False, dataset=None, cycles=[], blockers=[])

    def mark(key, state, detail):
        next(row for row in stages if row['id'] == key).update(state=state, detail=detail)

    def onward(label, **action):
        result['next'] = dict(label=label, **action)
        return result

    mark('application', 'waiting', '평가 근거를 검토한 뒤 별도 승인·장치 검증이 필요합니다.')
    total = sum(counts.get(state, 0) for state in ('approved', 'pending', 'excluded'))
    if not total:
        mark('data', 'waiting', '학습할 사진이나 영상을 등록하세요.')
        return onward('자료 등록', href='/catalog')
    mark('data', 'done', f'등록한 사진 {total}장')
    approved = pixel_counts.get('approved', 0)
    if not approved:
        mark('review', 'waiting', '픽셀 승인 0장 · 사진 전체와 배경을 확인해 승인하세요.')
        return onward('픽셀 검수 시작', href='/pixels?filter=pending')
    mark('review', 'done', f'픽셀 승인 {approved}장 · 승인된 자료만 준비합니다.')
    if not preparation or not preparation.get('current_decisions_match') or not preparation.get('pixel_frames'):
        mark('preparation', 'attention' if preparation else 'waiting',
             '검수 결정이 변경됐습니다. 다시 준비하세요.' if preparation else '현재 승인 자료를 준비하세요.')
        return onward('승인 자료 준비', action='prepare')
    mark('preparation', 'done', f"현재 결정과 일치 · 픽셀 {preparation['pixel_frames']}장")
    if not control or not control.get('available') or control.get('error'):
        mark('dataset', 'connection', (control or {}).get('error') or '이 작업대의 학습 실행기 연결이 필요합니다.')
        return onward('학습 실행기 연결 안내', href='#pipeline-setup')
    owner = control.get('pipeline') or {}
    matched = owner.get('authority') == result['identity']
    result['current'] = matched
    result['blockers'] = owner.get('blockers', [])
    if not matched or owner.get('status') == 'held' or not owner.get('dataset'):
        mark('dataset', 'attention' if owner.get('status') == 'held' else 'waiting',
             '입력 조건을 확인한 뒤 다시 시도하세요.' if owner.get('status') == 'held'
             else '실행기가 현재 검수 결정을 대조하고 데이터셋을 확인합니다.')
    else:
        result.update(dataset=owner['dataset'], cycles=owner.get('cycles', []))
        name, _, revision = owner['dataset'].partition('@')
        mark('dataset', 'done', f'{name} · 버전 {revision[:12]}')
        rows = result['cycles']
        bound = bool(rows) and all(row.get('dataset') == owner['dataset'] for row in rows)
        phases = [row['status'] for row in rows] if bound else []
        if bound and all(row['status'] in ('ready', 'candidate') and row.get('revision') for row in rows):
            mark('training', 'done', f'현재 자료의 모델 {len(rows)}개 생성')
            if all(phase == 'ready' for phase in phases):
                mark('evaluation', 'done', '소유 실행기의 평가·READY 기록 확인 · 장치 적용 전입니다.')
                return onward('모델·평가 근거 확인', href='#pipeline-evidence')
            mark('evaluation', 'waiting', '학습 후보 생성 완료 · 독립 평가 결과를 확인해야 합니다.')
            return onward('학습 후보 근거 확인', href='#pipeline-evidence')
        if 'running' in phases:
            mark('training', 'running', '현재 자료의 학습·평가를 처리하고 있습니다.')
        elif any(phase in ('retry', 'gave_up', 'rejected') for phase in phases):
            mark('training', 'attention', '현재 시도의 오류와 재시도 가능 여부를 확인하세요.')
            if 'rejected' in phases:
                mark('evaluation', 'attention', '품질 조건을 충족하지 못했습니다. 새 조건의 작업이 필요합니다.')
        else:
            mark('training', 'waiting', '현재 데이터셋의 학습 시도와 모델 기록을 기다리고 있습니다.')
    if control.get('active'):
        return onward('진행 상태 새로고침', action='refresh')
    if control.get('can_retry'):
        return onward('학습 입력 확인·재시도', action='retry')
    if control.get('can_start'):
        return onward('자동 학습 시작', action='start')
    return onward('실행 상태·오류 확인', href='#pipeline-evidence')
