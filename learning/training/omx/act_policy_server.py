"""D-969 step 5: an official LeRobot ACT checkpoint behind JSON lines on stdin/stdout, for the Isaac closed loop.

Isaac's SDK python has no LeRobot, so the policy runs in the isolated lerobot==0.4.4 environment and the task talks to it.
Observations and actions are in the dataset's units (isaac_demo_export.arm_units); LeRobot's own predict_action does the
image layout, normalization and de-normalization the trainer used.

  {"op": "reset"}                                                        -> {"ok": true}
  {"op": "act", "state": [12], "images": {name: {"shape": [H, W, 3], "b64": ...}}}   -> {"action": [12]}

  python act_policy_server.py --checkpoint <train out>/checkpoints/last/pretrained_model [--device cuda]
"""
import argparse
import base64
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'curation/omx'))


def main(argv=None, stdin=sys.stdin, stdout=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--device', default='cuda', choices=('cuda', 'cpu'))
    args = parser.parse_args(argv)
    sys.stdout = sys.stderr  # LeRobot and torch print while loading; stdout carries protocol lines only
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.utils.control_utils import predict_action
    from isaac_demo_export import TASK
    policy = ACTPolicy.from_pretrained(args.checkpoint).to(args.device)
    policy.eval()
    # The saved preprocessor moves inputs to the training device; a CPU-trained checkpoint served on CUDA mixed devices
    # (Isaac run 7d28). LeRobot's record loop overrides the device step the same way.
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(args.checkpoint),
                                         preprocessor_overrides={'device_processor': {'device': args.device}})
    device = torch.device(args.device)
    print(json.dumps({'ready': True, 'state_dim': policy.config.input_features['observation.state'].shape[0]}),
          file=stdout, flush=True)
    for line in stdin:
        request = json.loads(line)
        if request['op'] == 'reset':
            policy.reset()
            reply = {'ok': True}
        elif request['op'] == 'act':
            observation = {'observation.state': np.asarray(request['state'], np.float32)}
            for name, image in request['images'].items():
                observation['observation.images.'+name] = np.frombuffer(
                    base64.b64decode(image['b64']), np.uint8).reshape(image['shape'])
            action = predict_action(observation, policy, device, pre, post, False, TASK, 'bi_omx_follower')
            reply = {'action': [float(v) for v in action.cpu().numpy().reshape(-1)]}
        else:
            raise ValueError('unknown op')
        print(json.dumps(reply), file=stdout, flush=True)


if __name__ == '__main__':
    main()
