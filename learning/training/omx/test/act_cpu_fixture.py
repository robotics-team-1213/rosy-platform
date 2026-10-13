"""Synthetic zero-weight ACT fixture; never an approved/trained installation."""
from dataclasses import replace
import hashlib
import json

import pytest


def install_cpu_fixture(session, root):
    torch = pytest.importorskip('torch')
    pytest.importorskip('lerobot')
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.configs.types import PolicyFeature, FeatureType
    from rosy.contracts.learning import seal
    from rosy.execution.local.policy_install import InstallBinding, load_policy
    from act_inference import ACTInference
    from test_act_inference import artifact
    torch.set_num_threads(2)
    doc = session.policy.recheck()
    inputs = root.parent/'model-inputs'
    inputs.mkdir()
    _, template, payloads = artifact(inputs)
    for name, raw in payloads.items():
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    config = ACTConfig(input_features={
        'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
        'observation.images.front': PolicyFeature(FeatureType.VISUAL, (3,8,8))},
        output_features={'action': PolicyFeature(FeatureType.ACTION, (2,))},
        chunk_size=4, n_action_steps=4, dim_model=64, n_heads=4, dim_feedforward=256,
        n_encoder_layers=1, n_decoder_layers=1, use_vae=False, dropout=0.,
        pretrained_backbone_weights=None, device='cpu')
    model = ACTPolicy(config)
    with torch.no_grad():
        for parameter in model.parameters(): parameter.zero_()
    model.save_pretrained(root/'policy')
    doc.update(files=[dict(path=p.relative_to(root).as_posix(), bytes=p.stat().st_size,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted((root/'policy').iterdir())],
        normalization=template['normalization'], evaluations=template['evaluations'],
        cameras=[dict(template['cameras'][0], identity='cam-front')])
    doc = seal(doc)
    (root/'policy-artifact.json').write_text(json.dumps(doc), encoding='utf-8')
    binding = session.policy.binding
    binding = InstallBinding(policy_revision=doc['revision'], profile=binding.profile,
        robot_type=binding.robot_type, environment=binding.environment,
        device_profile_revision=binding.device_profile_revision,
        camera_profile_revision=binding.camera_profile_revision, owner=doc['owner'],
        cameras=doc['cameras'], normalization_sha256=doc['normalization']['sha256'],
        action_names=binding.action_names, action_limits=binding.action_limits, timing=doc['timing'])
    session.policy = load_policy(root, binding)
    session._lease = replace(session.lease, policy_revision=doc['revision'])
    return ACTInference(root, doc['revision'], monotonic=session._clock)
