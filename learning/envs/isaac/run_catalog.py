"""Allowlisted experiment conditions, independent of transport and SDK imports."""
import copy


_CATALOG = [
    {'id': 'omx-f-import', 'name': 'OMX-F 모델 연결 검사', 'implemented': True,
     'stage': 'model_import', 'seed_effect': 'NOT_USED_BY_MODEL_IMPORT',
     'timeout_seconds': 180,
     'requirements': ['승인 SDK·GPU·동일 계정의 두 학습 잠금 확인'],
     'reason': '모델·관절 검사이며 물리 집기 성공을 검증하지 않습니다.'},
    {'id': 'omx-map-stacking-rl', 'name': 'Confluence map: full-task two-arm PPO smoke',
     'implemented': True, 'stage': 'stacking_rl', 'seed_effect': 'INFEED_XY_AND_YAW',
     'timeout_seconds': 900, 'requirements': ['Approved SDK and model GPU', 'RSL-RL PPO'],
     'reason': 'Direct joint policy on the verified map geometry; training execution is separate from task proficiency.'},
    {'id': 'omx-map-long-stack', 'name': 'Confluence map: two-arm three-layer physical stacking',
     'implemented': True, 'stage': 'mapped_long_stack', 'seed_effect': 'INFEED_XY_AND_YAW',
     'timeout_seconds': 900, 'requirements': ['Approved SDK and model GPU'],
     'reason': 'Nominal photo cell poses; deterministic contact reference, not learned or hardware accepted.'},
    {'id': 'omx-stacking-rl', 'name': 'OMX-F 두 팔 90 mm 적재 PPO 구동 검사',
     'implemented': True, 'stage': 'stacking_rl', 'seed_effect': 'CARGO_RESET_XY_AND_YAW',
     'timeout_seconds': 900, 'requirements': ['승인 SDK·GPU·학습 잠금', 'RSL-RL 5.5 PPO'],
     'reason': '합성 두 팔·이동 벨트·3 cm 화물의 짧은 PPO 실행이며 적층 숙련·실물 수용이 아닙니다.'},
    {'id': 'pinky-conveyor-roundtrip', 'name': 'Pinky 정지 적재면 ↔ 컨베이어 왕복',
     'implemented': True, 'stage': 'contact_roundtrip',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 180,
     'requirements': ['승인 SDK·GPU·학습 잠금', '실측 좌표가 아닌 고정 SIM tray proxy'],
     'reason': '정지한 지지면과 CAD 집게의 접촉 왕복이며 학습 정책·실물 수용이 아닙니다.'},
    {'id': 'arm-s-cell-nominal', 'name': '공급암 S 셀: 상자를 벨트에 놓기', 'implemented': True, 'stage': 'arm_s_cell',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 600,
     'requirements': ['승인 SDK·GPU·학습 잠금', '실물 집기의 순기구학 좌표(카메라 정합 아님)'],
     'reason': '공급암 S 실물 청크 프레임을 받침·벨트·Pinky 프레임에 재생합니다. 학습 정책·실물 수용이 아닙니다.'},
    {'id': 'arm-s-cell-overhang', 'name': '공급암 S 셀: 상자 가장자리가 Pinky 프레임에 걸리는 놓기', 'implemented': True, 'stage': 'arm_s_cell',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 600,
     'requirements': ['승인 SDK·GPU·학습 잠금', '실물 집기의 순기구학 좌표(카메라 정합 아님)'],
     'reason': '공급암 S 실물 청크 프레임을 받침·벨트·Pinky 프레임에 재생합니다. 학습 정책·실물 수용이 아닙니다.'},
    {'id': 'arm-s-cell-wrong-yaw', 'name': '공급암 S 셀: 돌아간 상자를 사이트 각도로 집기', 'implemented': True, 'stage': 'arm_s_cell',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 600,
     'requirements': ['승인 SDK·GPU·학습 잠금', '실물 집기의 순기구학 좌표(카메라 정합 아님)'],
     'reason': '공급암 S 실물 청크 프레임을 받침·벨트·Pinky 프레임에 재생합니다. 학습 정책·실물 수용이 아닙니다.'},
    {'id': 'arm-s-cell-case', 'name': '공급암 S 셀: 실물 사례 재현', 'implemented': True, 'stage': 'arm_s_cell',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 600,
     'requirements': ['승인 SDK·GPU·학습 잠금', 'deploy/robot/omx/cell_cases.py 사례(상자 위치·회전, 놓을 곳, 집게 각도)'],
     'reason': '실물 셀에서 멈춘 사례를 같은 청크 프레임으로 재현합니다. 학습 정책·실물 수용이 아닙니다.'},
    {'id': 'port-e0-pick-place', 'name': '항만 E0 한 상자 집기·놓기',
     'implemented': False, 'stage': 'planned',
     'reason': 'source tray·제어기·그리퍼·독립 파지 판정 연결이 필요합니다.'},
    {'id': 'port-mixed-stacking', 'name': '혼합 1층·3층 적층',
     'implemented': False, 'stage': 'planned',
     'reason': 'D-826 E0와 단계별 물리 검증을 먼저 통과해야 합니다.'},
    {'id': 'port-retrieval', 'name': '야드 적재·회수 비교',
     'implemented': False, 'stage': 'planned',
     'reason': '공통 grid·회수·재배치·버퍼 판정기를 연결해야 합니다.'},
    {'id': 'port-cooperative-recovery', 'name': '양팔 협응 복구 비교',
     'implemented': False, 'stage': 'planned',
     'reason': 'fault replay·각 대조군·협응 안전 전제가 필요합니다.'},
]


def catalog() -> list[dict]:
    return copy.deepcopy(_CATALOG)


def normalize(scenario_id: str, config: dict) -> dict:
    entry = next((row for row in _CATALOG if row['id'] == scenario_id), None)
    if entry is None or not entry['implemented']:
        raise ValueError('scenario is unavailable' if entry is None else entry['reason'])
    keys = {'seed', 'case'} if scenario_id == 'arm-s-cell-case' else {'seed'}
    if (not isinstance(config, dict) or set(config) != keys
            or type(config['seed']) is not int or not 0 <= config['seed'] <= 2147483647):
        raise ValueError('settings require an integer seed in 0..2147483647'
                         + (' and a case' if scenario_id == 'arm-s-cell-case' else ' only'))
    if scenario_id == 'omx-map-stacking-rl':
        return {'model': 'omx_f', 'headless': True, 'seed': config['seed'],
                'fixture': 'confluence-map-stacking-rl-v1', 'iterations': 32, 'num_envs': 1}
    if scenario_id == 'omx-map-long-stack':
        return {'model': 'omx_f', 'headless': True, 'seed': config['seed'],
                'fixture': 'confluence-map-long-stack-v1', 'trials': 3}
    if scenario_id == 'omx-stacking-rl':
        return {'model': 'omx_f', 'headless': True, 'seed': config['seed'],
                'fixture': 'omx-stacking-v1', 'iterations': 32, 'num_envs': 1}
    if scenario_id == 'arm-s-cell-case':
        from arm_s_cell_fixture import check_case
        return {'model': 'omx_f', 'headless': True, 'seed': config['seed'], 'fixture': 'arm-s-cell-v1',
                'scenario': 'case', 'case': check_case(config['case'])}
    if scenario_id == 'pinky-conveyor-roundtrip':
        return {'model': 'omx_f', 'headless': True, 'frames': 4800, 'seed': config['seed'],
                'fixture': 'stationary-proxy-v3'}
    if scenario_id.startswith('arm-s-cell-'):
        return {'model': 'omx_f', 'headless': True, 'seed': config['seed'], 'fixture': 'arm-s-cell-v1',
                'scenario': scenario_id.removeprefix('arm-s-cell-')}
    return {'model': 'omx_f', 'headless': True, 'frames': 120, 'seed': config['seed']}
