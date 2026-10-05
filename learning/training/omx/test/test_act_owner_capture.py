"""Private learning composition; fake predictor/clock are not inference/device proof."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/p) for p in ('learning/training/omx',
    'learning/training/omx/test', 'middleware/execution/local/test')]
from test_omx_policy_session import setup_session, CameraSnapshot
from test_act_inference import artifact
from act_inference import ACTInference
from act_owner_capture import CapturedRGB, infer_for_owner
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.contracts.learning import seal


def case(tmp_path, monkeypatch, *, enabled=True):
    session, client, clock, authority, root = setup_session(tmp_path, enabled=enabled, camera=True)
    source, modeldoc, data = artifact(tmp_path)
    old = session.policy.recheck()
    for name, raw in data.items():
        p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    doc = dict(old, files=modeldoc['files'], normalization=modeldoc['normalization'],
               evaluations=modeldoc['evaluations'])
    doc['cameras'] = [dict(modeldoc['cameras'][0], identity='cam-front')]
    doc = seal(doc)
    (root/'policy-artifact.json').write_text(json.dumps(doc))
    b = session.policy.binding
    binding = InstallBinding(policy_revision=doc['revision'], profile=b.profile,
        robot_type=b.robot_type, environment=b.environment,
        device_profile_revision=b.device_profile_revision, camera_profile_revision=b.camera_profile_revision,
        owner=doc['owner'], cameras=doc['cameras'], normalization_sha256=doc['normalization']['sha256'],
        action_names=b.action_names, action_limits=b.action_limits, timing=b.timing)
    session.policy = load_policy(root, binding)
    session._lease = replace(session.lease, policy_revision=doc['revision'])
    rgb = bytearray(range(192))
    camera = [CameraSnapshot('front', 'cam-front', 'a'*64, (3,8,8),
                            10_000_000_000, hashlib.sha256(rgb).hexdigest())]
    session._cameras = lambda: tuple(camera)
    seen = []
    def model(*_):
        def predict(obs):
            seen.append(obs)
            return [(.101+i*.001, .001) for i in range(4)]
        return predict
    monkeypatch.setattr('act_inference._model_from_bytes', model)
    engine = ACTInference(root, doc['revision'], monotonic=session._clock)
    return session, engine, CapturedRGB(camera[0], rgb), client, clock, authority, camera, seen, root


def test_exact_capture_and_candidate_reaches_existing_owner(tmp_path, monkeypatch):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch)
    candidate, result = infer_for_owner(engine, session, packet)
    assert seen == [result.source]
    assert result.source.positions == (.1, 0.)
    assert result.source.frame_sha256 == packet.metadata.frame_sha256
    assert not client.commands  # Adapter never submits or mints authority.
    assert session.submit(candidate).accepted
    assert client.commands[0].source_state_sequence == result.source.sequence == 10


@pytest.mark.parametrize('change', ['bytes', 'timestamp', 'identity'])
def test_replaced_capture_rejected_before_predict(tmp_path, monkeypatch, change):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch)
    if change == 'bytes':
        with pytest.raises(ValueError): CapturedRGB(packet.metadata, b'\0'*192)
        return
    metadata = replace(packet.metadata, **({'received_at_ns': 10_000_000_001}
                       if change == 'timestamp' else {'identity': 'other-camera'}))
    with pytest.raises(ValueError): infer_for_owner(engine, session, CapturedRGB(metadata, packet.rgb))
    assert not seen and not client.commands


def test_mutable_capture_copied_and_queue_not_relabelled(tmp_path, monkeypatch):
    session, engine, packet, _, clock, _, cameras, seen, _ = case(tmp_path, monkeypatch)
    first, result = infer_for_owner(engine, session, packet)
    clock[0] += .001
    cameras[0] = replace(cameras[0], received_at_ns=10_001_000_000)
    queued, later = infer_for_owner(engine, session, CapturedRGB(cameras[0], packet.rgb))
    assert len(seen) == 1 and not later.consumed_current
    assert queued.sequence == first.sequence
    assert queued.camera_received_at_ns == first.camera_received_at_ns
    assert later.source == result.source and queued.produced_at_ns == first.produced_at_ns


@pytest.mark.parametrize('fault', ['revoked', 'expired', 'artifact'])
def test_changes_during_inference_rejected_by_final_owner(tmp_path, monkeypatch, fault):
    session, engine, packet, client, clock, authority, _, seen, root = case(tmp_path, monkeypatch)
    original = engine._predict
    def predict(obs):
        actions = original(obs)
        if fault == 'revoked': authority[0] = False
        elif fault == 'expired': clock[0] = 11.
        else: (root/'policy/model.safetensors').write_bytes(b'changed')
        return actions
    engine._predict = predict
    with pytest.raises((PermissionError, ValueError)):
        candidate, _ = infer_for_owner(engine, session, packet)
        session.submit(candidate)
    assert not client.commands
    assert len(seen) == 1


def test_same_clock_and_exact_policy_required(tmp_path, monkeypatch):
    session, engine, packet, client, *_ = case(tmp_path, monkeypatch)
    engine._clock = lambda: 10.
    with pytest.raises(ValueError): infer_for_owner(engine, session, packet)
    assert not client.commands


def test_disabled_owner_rejects_before_predict(tmp_path, monkeypatch):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch, enabled=False)
    with pytest.raises(PermissionError): infer_for_owner(engine, session, packet)
    assert not seen and not client.commands


def test_capture_buffer_is_frozen(tmp_path, monkeypatch):
    _, _, packet, *_ = case(tmp_path, monkeypatch)
    mutable = bytearray(packet.rgb)
    frozen = CapturedRGB(packet.metadata, mutable)
    mutable[0] ^= 255
    assert frozen.rgb == packet.rgb


def test_lease_change_during_prediction_cannot_relabel_result(tmp_path, monkeypatch):
    session, engine, packet, client, *_ = case(tmp_path, monkeypatch)
    original = engine._predict
    def predict(obs):
        actions = original(obs)
        session._lease = replace(session.lease, lease_id='other')
        return actions
    engine._predict = predict
    with pytest.raises(ValueError, match='lease'): infer_for_owner(engine, session, packet)
    assert not client.commands


def test_queued_old_source_is_not_refreshed_to_pass_owner(tmp_path, monkeypatch):
    session, engine, packet, client, clock, _, cameras, _, _ = case(tmp_path, monkeypatch)
    infer_for_owner(engine, session, packet)
    clock[0] += .06  # Original 50ms guard is unchanged.
    from omx_adapter.command_owner import JointStateSnapshot
    session.observe(JointStateSnapshot({'joint_1':.1, 'joint_2':0.}, 11, clock[0], 'cal-7'))
    cameras[0] = replace(cameras[0], received_at_ns=int(clock[0]*1e9))
    candidate, result = infer_for_owner(engine, session, CapturedRGB(cameras[0], packet.rgb))
    assert not result.consumed_current and candidate.sequence == 10
    with pytest.raises(PermissionError): session.submit(candidate)
    assert not client.commands


def test_actual_cpu_model_composition_is_numeric_only(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    pytest.importorskip('lerobot')
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.configs.types import PolicyFeature, FeatureType
    session, _, packet, client, _, _, _, _, root = case(tmp_path, monkeypatch)
    monkeypatch.undo()  # Use the real byte-loaded CPU predictor, not the host fake.
    torch.set_num_threads(2)
    config = ACTConfig(input_features={
        'observation.state': PolicyFeature(FeatureType.STATE,(2,)),
        'observation.images.front': PolicyFeature(FeatureType.VISUAL,(3,8,8))},
        output_features={'action':PolicyFeature(FeatureType.ACTION,(2,))},
        chunk_size=4,n_action_steps=4,dim_model=64,n_heads=4,dim_feedforward=256,
        n_encoder_layers=1,n_decoder_layers=1,use_vae=False,dropout=0.,
        pretrained_backbone_weights=None,device='cpu')
    model = ACTPolicy(config)
    with torch.no_grad():
        for parameter in model.parameters(): parameter.zero_()
    doc = session.policy.recheck()
    model.save_pretrained(root/'policy')
    doc['files'] = [dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted((root/'policy').iterdir())]
    doc = seal(doc)
    (root/'policy-artifact.json').write_text(json.dumps(doc))
    b = session.policy.binding
    b = InstallBinding(policy_revision=doc['revision'], profile=b.profile, robot_type=b.robot_type,
        environment=b.environment,device_profile_revision=b.device_profile_revision,
        camera_profile_revision=b.camera_profile_revision,owner=b.owner,cameras=b.cameras,
        normalization_sha256=b.normalization_sha256,action_names=b.action_names,
        action_limits=b.action_limits,timing=b.timing)
    session.policy = load_policy(root,b)
    session._lease = replace(session.lease,policy_revision=doc['revision'])
    engine = ACTInference(root,doc['revision'],monotonic=session._clock)
    candidate, result = infer_for_owner(engine,session,packet)
    assert result.consumed_current and result.positions == (0.,0.)
    assert result.source.rgb == packet.rgb and candidate.camera_frames == (packet.metadata.frame_sha256,)
    assert not client.commands  # Real CPU model, synthetic fixture; no dispatch/learned quality grant.
