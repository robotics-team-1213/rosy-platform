"""D-866 P0 child pieces that run without a GPU, LeRobot or ROS: clamp, camera keys and the SIM-probe gate."""
import base64
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'integrations/robots/omx/src'), str(Path(__file__).resolve().parent)]
import policy_chain_vla_child as child  # noqa: E402

LIMITS = [(-1.0, 1.0), (-0.5, 0.5)]


def test_clamp_keeps_step_and_limits():
    assert child.clamp([0.9, -0.9], [0.0, -0.48], LIMITS, 0.04) == pytest.approx([0.04, -0.5])
    assert child.clamp([0.01, 0.2], [0.0, 0.0], LIMITS, 0.04) == pytest.approx([0.01, 0.04])


class Client:
    is_connected = True

    def __init__(self, simulation=True, names=('front', 'top')):
        self.info = {'joint_names': ['joint1', 'joint2'], 'simulation': simulation}
        self.names, self.sent = names, []

    def get_observation(self):
        frame = base64.b64encode(bytes(12)).decode()
        return {'positions': {'joint1': 0.0, 'joint2': 0.1},
                'cameras': [{'name': n, 'shape': [3, 2, 2], 'rgb_base64': frame} for n in self.names]}

    def send_action(self, positions):
        self.sent.append(positions)


def target(client):
    return child.SimProbeTarget(client, policy_type='smolvla', limits=LIMITS, max_step=0.04)


def test_cameras_are_renamed_to_checkpoint_keys_and_submit_is_clamped():
    client = Client()
    probe = target(client)
    observation = probe.observe()
    assert set(observation['images']) == {'camera1', 'camera2'}
    probe.submit({'joint1': 0.5, 'joint2': 0.1})
    assert client.sent == [{'joint1': pytest.approx(0.04), 'joint2': pytest.approx(0.1)}]
    assert probe.last['raw'] == [0.5, 0.1]


def test_missing_or_extra_camera_is_refused_before_inference():
    with pytest.raises(ValueError):
        target(Client(names=('front',))).observe()


def test_probe_type_needs_a_sim_core():
    with pytest.raises(PermissionError):
        target(Client(simulation=False))
