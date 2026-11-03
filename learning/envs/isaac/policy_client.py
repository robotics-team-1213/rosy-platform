"""D-969 step 5: the Isaac side of a learned policy. Starts learning/training/omx/act_policy_server.py in the isolated
LeRobot environment and exchanges JSON lines with it (Isaac's SDK python has no LeRobot).

A case names its checkpoint by content: fixture['policy'] = dict(env=<venv name>, model_sha256=<model.safetensors sha256>);
the model PC keeps it at ~/rosy-learning/policies/<sha256>/ and the environment at ~/rosy-learning/<env>/. Nothing runs
unless the bytes match.
"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
STORE = Path.home()/'rosy-learning'


def start(spec, views):
    """(client, observe) for a policy case: observe() renders the real-camera views at the training image size, as the
    exporter made them (D-969 step 5)."""
    import numpy as np
    from PIL import Image

    def observe():
        size = tuple(spec['image_size'])
        return {view: np.asarray(Image.fromarray(camera.get_rgba()[:, :, :3].astype(np.uint8)).resize(size, Image.BOX))
                for view, camera in views.items()}
    return PolicyClient(spec), observe


class PolicyClient:
    def __init__(self, spec, *, device='cuda', store=STORE, python=None, server=ROOT/'learning/training/omx/act_policy_server.py'):
        checkpoint = store/'policies'/spec['model_sha256']
        weights = (checkpoint/'model.safetensors').read_bytes()
        if hashlib.sha256(weights).hexdigest() != spec['model_sha256']:
            raise ValueError('policy checkpoint bytes differ from the case')
        python = python or str(store/spec['env']/'bin/python')
        self.process = subprocess.Popen([python, str(server),
                                         '--checkpoint', str(checkpoint), '--device', device],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        ready = self._read()
        if not ready.get('ready') or ready.get('state_dim') != 12:
            raise ValueError('policy server did not start for a 12-joint two-arm state')

    def _read(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f'policy server exited ({self.process.poll()})')
        return json.loads(line)

    def _ask(self, request):
        self.process.stdin.write(json.dumps(request)+'\n')
        return self._read()

    def reset(self):
        self._ask({'op': 'reset'})

    def act(self, state, images):
        """state: 12 arm units; images: {name: HxWx3 uint8 array} -> 12 arm units."""
        reply = self._ask({'op': 'act', 'state': [float(v) for v in state], 'images': {
            name: {'shape': list(image.shape), 'b64': base64.b64encode(image.tobytes()).decode()} for name, image in images.items()}})
        action = reply['action']
        if len(action) != 12:
            raise ValueError('policy action is not 12 joints')
        return action

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
