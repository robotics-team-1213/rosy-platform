"""Fixture ladder roots shared by the ladder HTTP and browser tests."""
import json
import sys

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16


def record(round_id, *, placed=12, n=50, mujoco='passed', seed=100000, parent=None):
    low = {12: 0.146, 40: 0.67, 2: 0.011}.get(placed, 0.1)
    return {
        'schema': 'rosy.omx-ladder-round.v1', 'round_id': round_id, 'created_at': '2026-11-07T03:00:00+09:00',
        'parent_round_id': parent, 'source_sha': 'a' * 40,
        'scene': {'robot': 'arm_b', 'jaw': 'palletizing-v2.1', 'wrist_camera': 'omx-ai-stock', 'revision': 'r1'},
        'recipe': {'policy': 'act', 'steps': 20000, 'batch_size': 8, 'chunk_size': 30, 'n_action_steps': 8, 'optimizer_lr': 1e-5},
        'data': {'episodes': 60, 'from_failures': 0},
        'stages': {
            'mujoco': {'status': mujoco, 'claim': '기하: 도달·순서·충돌', 'reason': None if mujoco == 'passed' else '평가 실패',
                       'eval': {'n': n, 'seed_base': seed, 'strict': {'placed': placed, 'wilson_low': low},
                                'loose': {'placed': 45}, 'lifted': 48, 'xy_err_mm_median': 9.1, 'yaw_err_deg_median': 2.0},
                       'artifacts': [{'name': 'top.png', 'path': 'artifacts/top.png', 'kind': 'image'}]},
            'gazebo': {'status': 'blocked', 'claim': 'ROS 실행 계약', 'contract': None, 'artifacts': [],
                       'reason': 'Gazebo 시험 PC에 연결되지 않았습니다.'},
            'isaac': {'status': 'not_run', 'claim': '접촉·영상', 'run_id': None, 'result': None, 'artifacts': [],
                      'reason': 'Isaac 실행을 아직 요청하지 않았습니다.'}}}


def make_root(base, rounds=None):
    """rounds: {round_id: record kwargs}; returns the ladder root."""
    root = base / 'ladder'
    for round_id, kwargs in (rounds or {}).items():
        folder = root / 'rounds' / round_id
        (folder / 'artifacts').mkdir(parents=True)
        (folder / 'round.json').write_text(json.dumps(record(round_id, **kwargs)), encoding='utf-8')
        (folder / 'artifacts' / 'top.png').write_bytes(PNG)
    (root / 'rounds').mkdir(parents=True, exist_ok=True)
    return root


def config(base, root):
    return {'root': str(root), 'cell': str(base / 'cell'), 'python': sys.executable, 'lerobot_train': str(base / 'lerobot-train')}
