"""Allowlisted experiment conditions, independent of transport and SDK imports."""
import copy


_CATALOG = [
    {'id': 'omx-f-import', 'name': 'OMX-F 모델 연결 검사', 'implemented': True,
     'stage': 'model_import', 'seed_effect': 'NOT_USED_BY_MODEL_IMPORT',
     'timeout_seconds': 180,
     'requirements': ['승인 SDK·GPU·동일 계정의 두 학습 잠금 확인'],
     'reason': '모델·관절 검사이며 물리 집기 성공을 검증하지 않습니다.'},
    {'id': 'pinky-conveyor-roundtrip', 'name': 'Pinky 정지 적재면 ↔ 컨베이어 왕복',
     'implemented': True, 'stage': 'contact_roundtrip',
     'seed_effect': 'NOT_USED_BY_FIXED_FIXTURE', 'timeout_seconds': 180,
     'requirements': ['승인 SDK·GPU·학습 잠금', '실측 좌표가 아닌 고정 SIM tray proxy'],
     'reason': '정지한 지지면과 CAD 집게의 접촉 왕복이며 학습 정책·실물 수용이 아닙니다.'},
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
    if (not isinstance(config, dict) or set(config) != {'seed'}
            or type(config['seed']) is not int or not 0 <= config['seed'] <= 2147483647):
        raise ValueError('settings require only an integer seed in 0..2147483647')
    if scenario_id == 'pinky-conveyor-roundtrip':
        return {'model': 'omx_f', 'headless': True, 'frames': 4800, 'seed': config['seed'],
                'fixture': 'stationary-proxy-v2'}
    return {'model': 'omx_f', 'headless': True, 'frames': 120, 'seed': config['seed']}
