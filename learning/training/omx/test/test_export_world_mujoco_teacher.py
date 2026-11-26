"""Check format conversion without relying on a lab OpenGL context."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_dataset import load_dataset
from export_world_mujoco_teacher import export


def test_export_uses_disjoint_physics_resets_and_radian_camera_data(tmp_path):
    class Cell:
        qadr = [0]

        def reset(self, seed):
            self.seed = seed
            self.qpos = np.array([0.1 + seed % 10 / 10])
            return self, None, None

        def body(self, name):
            return SimpleNamespace(xpos=[0, 0, 1])

        def teacher(self, *_args):
            return [np.array([0.3]), np.array([0.6])]

        def views(self, _data):
            top = np.full((240, 320, 3), round(self.qpos[0] * 100), dtype=np.uint8)
            return top, top + 2

        def advance(self, _data, target):
            self.qpos[:] = target

        def judge(self, *_args):
            return {'strict': self.seed != 1000}

    root = tmp_path / 'teacher'
    receipt = export(Cell(), 'a' * 64, root, ['joint1'], 'place', 1, 1)
    checked = load_dataset(root)
    assert checked.source == 'scripted_teacher' and receipt['dataset_revision'] == checked.revision
    assert checked.profile['arms'][0]['units'] == 'rad'
    assert [(row['split'], row['seed'], row['strict_pass']) for row in receipt['attempts']] == [
        ('train', 1000, False), ('train', 1001, True), ('eval', 100000, True),
    ]
    train = checked.split('train')[0]
    assert train.metadata['session_id'] == 'mujoco-1001'
    assert checked.split('eval')[0].metadata['session_id'] == 'mujoco-100000'
    np.testing.assert_allclose(train.arrays['observation.state'][:, 0], [0.2, 0.3])
    np.testing.assert_allclose(train.arrays['action'][:, 0], [0.3, 0.6])
    wrist = train.arrays['observation.images.wrist']
    assert wrist.shape == (2, 3, 60, 80) and wrist.dtype == np.uint8
    assert list(wrist[:, 0, 0, 0]) == [22, 32]
