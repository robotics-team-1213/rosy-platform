"""Home rows: every Learning domain on the same loop stages (D-857 §3), from data this workspace already holds.

Read-only. A stage nothing here can see is ``not_available`` with a Korean reason; no count is invented and
nothing is approved or promoted (D-514 §5, D-793). ⑦ 배포 is outside Learning and has no row.
"""
STAGES = (('collect', '수집'), ('label', '정답'), ('dataset', '데이터셋'), ('train', '학습'),
          ('evaluate', '평가'), ('promote', '승격 기록'))
NOT_CONNECTED = 'Learning에 연결 전'
DOMAINS = (('lane', 'Pinky 차로·픽셀'), ('object', 'Pinky 객체'), ('omx', 'OMX 모방학습'),
           ('sim', 'Isaac SIM'), ('vlm', 'VLM 판단'), ('decision', '판단 모델'))
# project() stage ids -> loop stage; a loop stage is done only when all its project stages are.
LANE = {'collect': ('data',), 'label': ('review',), 'dataset': ('preparation', 'dataset'),
        'train': ('training',), 'evaluate': ('evaluation',), 'promote': ('application',)}
LANE_STATE = {'done': 'done', 'running': 'active', 'waiting': 'waiting', 'attention': 'blocked', 'connection': 'blocked'}
SIM_TERMINAL = {'SUCCEEDED': 'done', 'STOPPED': 'done', 'FAILED': 'blocked', 'UNKNOWN': 'blocked'}


def go(label, href):
    return {'label': label, 'href': href}


def row(key, name, stages):
    """stages: {stage: (state, evidence, next)}; a stage left out is not_available."""
    rows = [dict(stage=stage, label=label, **dict(zip(('state', 'evidence', 'next'),
                 stages.get(stage, ('not_available', NOT_CONNECTED, None))))) for stage, label in STAGES]
    return {'id': key, 'name': name, 'stages': rows,
            'next': next((stage['next'] for stage in rows if stage['next']), None),
            'blocked': next((stage['evidence'] for stage in rows if stage['state'] in ('blocked', 'not_available')), None)}


def _lane_next(step):
    if step.get('href', '').startswith('#'):
        return go(step['label'], '/learning' + step['href'])
    if step.get('href'):
        return go(step['label'], step['href'])
    return go(step['label'], '/pixels#pixel-preparation' if step.get('action') == 'prepare' else '/learning#pipeline')


def lane(pipeline):
    by_id, stages, current = {stage['id']: stage for stage in pipeline['stages']}, {}, False
    for stage, keys in LANE.items():
        parts = [by_id[key] for key in keys]
        part = next((p for p in parts if p['state'] != 'done'), parts[-1])
        state, step = LANE_STATE.get(part['state'], 'blocked'), None
        if state != 'done' and not current:
            current, step = True, _lane_next(pipeline['next'])
            state = 'active' if state == 'waiting' else state
        stages[stage] = (state, part['detail'], step)
    return stages


def objects(counts, preparation):
    approved, pending, excluded = (counts.get(key, 0) for key in ('approved', 'pending', 'excluded'))
    stages = {'train': ('not_available', '객체 학습기가 아직 Learning에 없습니다.', None),
              'evaluate': ('not_available', '객체 평가 경로가 아직 Learning에 없습니다.', None)}
    if not approved + pending + excluded:
        return stages | {'collect': ('active', '등록한 사진이 없습니다.', go('자료 등록', '/catalog')),
                         'label': ('waiting', '사진을 등록하면 객체 검수를 합니다.', None),
                         'dataset': ('waiting', '승인한 객체가 생기면 준비합니다.', None)}
    stages['collect'] = ('done', f'사진 {approved + pending + excluded}장', None)
    evidence = f'객체 승인 {approved} · 대기 {pending} · 제외 {excluded}'
    if pending:
        stages['label'] = ('active', evidence, go('객체 검수', '/?filter=pending'))
    elif approved:
        stages['label'] = ('done', evidence, None)
    else:
        stages['label'] = ('blocked', '모든 사진이 제외됐습니다.', go('자료 등록', '/catalog'))
    if preparation and preparation.get('object_frames') and preparation.get('current_decisions_match'):
        stages['dataset'] = ('done', f"준비본 객체 {preparation['object_frames']}장", None)
    elif preparation and not preparation.get('current_decisions_match'):
        stages['dataset'] = ('blocked', '검수 결정이 바뀌었습니다. 다시 준비하세요.', go('승인 자료 준비', '/pixels#pixel-preparation'))
    elif approved and not pending:
        stages['dataset'] = ('active', '승인 객체를 준비하세요.', go('승인 자료 준비', '/pixels#pixel-preparation'))
    else:
        stages['dataset'] = ('waiting', '객체 검수를 마치면 준비합니다.', None)
    return stages


def omx(items, reviewed, tasks=0):
    """items: linked results (learning_links); reviewed: linked ids with a saved segment review;
    tasks: robot·task records of the task page (learning_tasks), where OMX policy training starts."""
    sets = {item['id'] for item in items if item['kind'] == 'omx'}
    train = (('active', f'학습 과제 {tasks}개', go('학습 과제', '/learning/tasks')) if tasks
             else ('waiting', '등록한 학습 과제가 없습니다.', go('학습 과제 등록', '/learning/tasks')))
    if not sets:
        return {'collect': ('active', '연결한 OMX 결과 폴더가 없습니다.', go('OMX 구간 검수', '/learning/omx')),
                'label': ('waiting', 'OMX 결과를 연결하면 구간을 검수합니다.', None), 'train': train}
    done = len(sets & set(reviewed))
    return {'collect': ('done', f'OMX 결과 폴더 {len(sets)}개', None),
            'label': ('done' if done == len(sets) else 'active', f'구간 검수 {done}/{len(sets)}',
                      None if done == len(sets) else go('OMX 구간 검수', '/learning/omx')),
            'dataset': ('not_available', '구간 JSON은 아직 CLI로 넘깁니다.', None), 'train': train}


def sim(runs):
    """runs: None when not configured, {'error': ...} when the adapter failed, else {'runs': [...]}."""
    if runs is None:
        return {'collect': ('not_available', 'SIM 실행 연결이 설정되지 않았습니다.', None)}
    if 'error' in runs:
        return {'collect': ('blocked', 'SIM 실행 연결을 확인하세요.', go('SIM 실험', '/learning/sim'))}
    if not runs['runs']:
        return {'collect': ('active', 'SIM 실험 기록이 없습니다.', go('SIM 실험 시작', '/learning/sim'))}
    latest = max(runs['runs'], key=lambda run: str(run.get('updated_at') or run.get('created_at') or ''))
    status = str(latest.get('status', ''))[:40]
    return {'collect': (SIM_TERMINAL.get(status, 'active'), f"실험 {len(runs['runs'])}회 · 최근 {status or '상태 없음'}",
                        go('SIM 결과 확인', '/learning/sim'))}


def vlm(counts, eval_url=None):
    """counts: None when this workspace has no VLM tables, else {total, labelled, excluded}."""
    if not counts or not counts['total']:
        if eval_url:
            return {'collect': ('not_available', 'VLM 정답은 별도 평가 state에 있습니다.', go('VLM 평가 state 열기', eval_url))}
        return {'collect': ('not_available', 'VLM 질문 자료가 없습니다.', None)}
    total, labelled = counts['total'], counts['labelled']
    pending = total - labelled - counts['excluded']
    return {'collect': ('done', f'질문 사진 {total}장', None),
            'label': ('active' if pending else 'done', f"확정 {labelled} · 미확정 {pending} (임시 정답 {counts['provisional']})",
                      go('VLM 정답 달기', '/learning/vlm') if pending else None),
            'dataset': ('not_available', 'VLM 정답은 평가용입니다(D-853).', None),
            'train': ('not_available', '질문·프롬프트 보정은 아직 화면 밖입니다.', None),
            'evaluate': ('done', f'확정 정답 {labelled}장 기준', go('VLM 평가 보기', '/learning/evaluate?domain=vlm'))
            if labelled else ('waiting', '확정 정답이 생기면 평가합니다.', None)}


def domains(*, pipeline, counts, preparation, items, omx_reviewed, sim_runs, vlm_counts, vlm_eval_url=None, tasks=0):
    sources = {'lane': lane(pipeline), 'object': objects(counts, preparation), 'omx': omx(items, omx_reviewed, tasks),
               'sim': sim(sim_runs), 'vlm': vlm(vlm_counts, vlm_eval_url), 'decision': {}}
    return [row(key, name, sources[key]) for key, name in DOMAINS]


def stored(db):
    """(OMX ids with a segment review, VLM counts or None, learning task count) from tables this database
    already has; creates none."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    reviewed = ([row[0] for row in db.execute('SELECT DISTINCT id FROM omx_segment_reviews')]
                if 'omx_segment_reviews' in tables else [])
    tasks = (db.execute("SELECT COUNT(*) FROM learning_task_records WHERE kind='task'").fetchone()[0]
             if 'learning_task_records' in tables else 0)
    if 'vlm_items' not in tables:
        return reviewed, None, tasks
    status = ({row[0]: row[1] for row in db.execute('SELECT status, COUNT(*) FROM vlm_labels GROUP BY status')}
              if 'vlm_labels' in tables else {})
    provisional = 0
    if {'vlm_model_answers', 'vlm_labels', 'vlm_audits'} <= tables:
        import vlm_judge  # only workspaces that hold VLM questions pay for the consensus
        paused = {qid for qid, entry in vlm_judge.audits(db).items() if entry['paused']}
        decided = {row[0] for row in db.execute('SELECT item FROM vlm_labels')}
        provisional = sum(1 for item, answers in vlm_judge.provisional(db).items()
                          if item not in decided and set(answers) - paused)
    return reviewed, {'total': db.execute('SELECT COUNT(*) FROM vlm_items').fetchone()[0], 'provisional': provisional,
                      'labelled': status.get('labelled', 0), 'excluded': status.get('excluded', 0)}, tasks
