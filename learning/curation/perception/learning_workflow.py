"""Task journey derived from explicit input bindings and owned run evidence."""
from copy import deepcopy
from urllib.parse import urlencode


def method_catalog(methods):
    rows = [
        dict(id='act', label='사람의 시연 따라 배우기', requirements=['저장 검수', '독립 평가 자료'],
             reason='ACT 학습 실행기 연결이 필요합니다.'),
        dict(id='hilserl', label='저장 경험으로 배우기',
             requirements=['다음 관측', '보상', '종료 신호', '행동 범위'],
             reason='저장 경험 SAC 실행기와 전이 자료가 필요합니다.'),
        dict(id='online_hilserl', label='실물에서 사람 개입으로 배우기',
             requirements=['실물 actor', '보상·성공 판정', '초기화', '개입·제어권 전환'],
             reason='과제의 실물 actor·보상·초기화 연결이 아직 없습니다.'),
        dict(id='vla', label='사전학습 모델을 내 과제에 맞추기',
             requirements=['기반 모델', '입출력 처리 호환성', '학습 자료·언어 지시'],
             reason='공통 과제의 VLA 미세조정 실행기가 아직 연결되지 않았습니다.'),
        dict(id='simulation', label='시뮬레이션에서 배우기',
             requirements=['환경·과제 버전', '관측·행동 계약', '독립 평가'],
             reason='SIM 실험은 별도 화면에서 실행하며 공통 과제 학습 연결이 필요합니다.'),
    ]
    for row in rows:
        available = row['id'] in ('act', 'hilserl') and methods.get(row['id'], {}).get('available') is True
        row['state'] = 'available' if available else 'unavailable'
        if available:
            row['reason'] = ''
        row['scope'] = 'offline_only'
    return dict(lerobot_version='0.4.4', methods=rows, physical_learning_verified=False,
        features=[
            dict(id='setup', label='로봇·조작기·센서 설정', state='partial',
                 supported='불변 팔·카메라 프로필과 녹화 준비서', missing='실물 연결·보정 확인'),
            dict(id='processors', label='관측·행동 처리', state='partial',
                 supported='native 모델 전처리·후처리기와 원본 단위 보존', missing='모든 정책·장치 처리기의 공통 편집'),
            dict(id='collection', label='조종·녹화·재생·검수', state='partial',
                 supported='기존 native 녹화·봉인·인계와 검수', missing='실물 브라우저 조종·녹화 transport'),
            dict(id='training', label='학습 실행과 중단', state='partial',
                 supported='ACT·저장 경험 SAC의 호스트 실행', missing='방법별 학습 재개·새 어댑터 수용'),
            dict(id='evaluation', label='추론·평가·적용 준비', state='partial',
                 supported='모델 재적재·독립 오프라인 평가·산출물', missing='실물 평가·적용 승인'),
            dict(id='storage', label='자료·모델 관리', state='partial',
                 supported='기존 자료 등록·Hub 가져오기·보관', missing='모든 native 자료의 브라우저 직접 업로드'),
        ])


def _bound(task, row):
    binding = row.get('binding')
    return isinstance(binding, dict) and binding.get('task_id') == task['id'] and all(
        binding.get(key) == expected for key, expected in (
            ('task_revision', task['revision']),
            ('profile_revision', task.get('profile_revision'))))


def _reviewed(row):
    if not row.get('available') or row.get('fixture_only'):
        return False
    whole = bool(row.get('latest_review_id')) and row.get('trainable', {}).get('ok') is True
    segments = row.get('segment_review', {}).get('version', 0) > 0 and row.get('segments_trainable', {}).get('ok') is True
    return whole or segments


def _owned_run(task, run):
    binding = run.get('learning_task')
    return (isinstance(binding, dict) and binding.get('task_id') == task['id']
            and binding.get('task_revision') == task['revision'])


def _evaluated(run):
    result = run.get('result') or {}
    evaluation = result.get('evaluation') or {}
    count = evaluation.get('samples', evaluation.get('frames', 0))
    return (run.get('status') == 'succeeded' and result.get('learning_task') == run.get('learning_task')
            and type(count) is int and count > 0
            and (run.get('execution_mode') != 'native_train'
                 or evaluation.get('model_reloaded_in_new_process') is True))


def project_task(task, inputs, runs, methods, host_id):
    associated = [deepcopy(row) for row in inputs if _bound(task, row)]
    for row in associated:
        if row['binding'].get('source_revision') != row.get('source_revision'):
            row['available'] = False
            row['error'] = '연결한 원본 revision이 바뀌었습니다. 원본과 검수를 다시 확인하세요.'
    owned = [deepcopy(run) for run in runs if _owned_run(task, run)]
    ready = [row for row in associated if _reviewed(row)]
    complete = [run for run in owned if _evaluated(run)]
    active = [run for run in owned if run.get('status') in ('launching', 'running', 'stopping')]
    failed = next((run for run in owned if run.get('status') in ('failed', 'interrupted', 'cancelled')), None)
    profile = (task.get('profile') or {}).get('profile') or {}
    setup = dict(profile_id=task.get('profile_id'), profile_revision=task.get('profile_revision'),
                 arms=deepcopy(profile.get('arms', [])), cameras=deepcopy(profile.get('cameras', [])),
                 device_verified=False, calibration_verified=False)
    recording = dict(available=False, task_card_export=True, scope='preparation_only',
        local_workspace='/learning/record',
        reason='로컬 녹화 작업대에서 소스 준비 상태를 확인하거나 기존 native 녹화 담당자에게 준비서를 전달하세요.')
    catalog = method_catalog(methods)
    task_methods = deepcopy(catalog['methods'])
    act = task_methods[0]
    if not ready or host_id not in ('model', 'ai'):
        act.update(state='unavailable', reason='과제에 연결한 시연의 저장 검수와 학습 호스트 확인이 필요합니다.')
    # SAC is a separate expert path: native demonstrations do not invent reward or next-state data.
    task_methods[1].update(state='unavailable', reason='저장 경험 자료를 전문가 실행 화면에서 검증·선택하세요.')
    reason = None
    if active:
        stage, kind, label, href = 'learn', 'learn', '진행 중인 학습 확인', '#workflow-results'
    elif complete:
        stage, kind, label, href = 'results', 'results', '완료된 학습과 평가 확인', '#workflow-results'
    elif not task.get('runnable') or not profile:
        stage, kind, label = 'prepare', 'configure', '로봇과 과제 설정 확인'
        href = '/learning/tasks/manage?' + urlencode({'task': task['id']}) + '#task-title'
        reason = task.get('blocked_reason') or '실행 가능한 과제·팔·카메라 설정이 필요합니다.'
    elif not associated:
        stage, kind, label, href = 'record', 'attach', '직접 조종·녹화 준비 또는 기존 시연 연결', '#workflow-record'
        reason = recording['reason']
    elif not ready:
        stage, kind, label = 'review', 'review', '연결한 시연의 저장 검수 확인'
        href = '/learning/omx?' + urlencode({'task': task['id'], 'prepared': associated[0]['prepared_id']}) + '#dataset-section'
        reason = next((row.get('error') for row in associated if row.get('error')), None)
        reason = reason or '원본·저장 검수·독립 학습/평가 분할을 다시 확인하세요.'
    else:
        stage, kind, label, href = 'learn', 'learn', '저장 검수로 학습 준비', '#workflow-learn'
        if act['state'] != 'available':
            reason = act['reason']
        elif failed:
            reason = '앞선 작업이 중단되거나 실패했습니다. 결과를 확인하고 새 작업으로 시작하세요.'
    completion = dict(recording_complete=False, review_complete=bool(ready),
        training_complete=bool(complete), offline_evaluation_complete=bool(complete),
        physical_evaluation_complete=False, application_approved=False)
    return dict(task_id=task['id'], task_revision=task['revision'], stage=stage, blocked_reason=reason,
        next_action=dict(kind=kind, label=label, href=href), completion=completion,
        inputs=associated, runs=owned, setup=setup, methods=task_methods, recording=recording)
