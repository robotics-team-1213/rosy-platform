"""Private learning composition; fake predictor/clock are not inference/device proof."""
from dataclasses import dataclass, replace
from contextlib import nullcontext, contextmanager
import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/p) for p in ('learning/training/omx',
    'learning/training/omx/test', 'middleware/robot_execution/local/test', 'deploy/robot/omx')]
from test_omx_policy_session import setup_session, CameraSnapshot
from sim_policy_inference import infer_for_owner
from test_act_inference import artifact
from act_inference import ACTInference
from act_owner_capture import infer_captured
from rosy.execution.local.omx_policy import PolicyCandidate
from rosy.execution.local.policy_install import InstallBinding, InstalledPolicy, load_policy
from rosy.contracts.learning import seal


@dataclass(frozen=True)
class CapturedRGB:
    # Test caller's retained capture pair, not a trust/owner API.
    metadata: CameraSnapshot
    rgb: bytes

    def capture(self):
        return nullcontext(self)


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
    timings = {}
    candidate, result = infer_for_owner(engine, session, packet, timings=timings)
    assert timings and all(value >= 0 for value in timings.values())
    assert seen == [result.source]
    assert result.source.positions == (.1, 0.)
    assert result.source.frame_sha256 == packet.metadata.frame_sha256
    assert not client.commands  # Adapter never submits or mints authority.
    assert session.submit(candidate).accepted
    assert client.commands[0].source_state_sequence == result.source.sequence == 10


@pytest.mark.parametrize('refresh', [True, False])
def test_aged_capture_is_replaced_before_computation_or_stops(tmp_path, monkeypatch, refresh):
    session, engine, packet, client, clock, _, cameras, seen, _ = case(tmp_path, monkeypatch)
    clock[0] += .02  # Valid under 50ms admission, but leaves little computation margin.
    pauses=[]
    class LiveCamera:
        def capture(self):
            return nullcontext(CapturedRGB(cameras[0], packet.rgb))
    def pause(delay):
        pauses.append(delay)
        clock[0] += delay
        if refresh:
            session.observe(replace(session._snapshot, sequence=11, received_at=clock[0]))
            cameras[0]=replace(cameras[0], received_at_ns=int(clock[0]*1e9))
    monkeypatch.setattr('sim_policy_inference.sleep', pause, raising=False)
    if refresh:
        candidate, result=infer_for_owner(engine, session, LiveCamera())
        assert pauses and len(seen)==1
        assert result.source.sequence==candidate.sequence==11
        assert candidate.observed_at_ns==int(clock[0]*1e9)
        assert candidate.camera_received_at_ns==(cameras[0].received_at_ns,)
    else:
        with pytest.raises((PermissionError, TimeoutError)):
            infer_for_owner(engine, session, LiveCamera())
        assert pauses and not seen
    assert not client.commands


def test_fresh_capture_after_attempt_deadline_never_computes(tmp_path, monkeypatch):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch)
    ticks=[0]
    monkeypatch.setattr('sim_policy_inference.perf_counter_ns', lambda: ticks[0])
    capture=session.capture_inference_input
    def delayed_capture(*args):
        observation=capture(*args)
        ticks[0]+=session.policy.binding.timing['max_observation_age_ns']
        return observation
    monkeypatch.setattr(session, 'capture_inference_input', delayed_capture)
    with pytest.raises(TimeoutError, match='capture margin'):
        infer_for_owner(engine, session, packet)
    assert not seen and not client.commands


def test_actor_budget_can_wait_for_a_new_fresh_capture(tmp_path, monkeypatch):
    session, engine, packet, client, clock, _, cameras, seen, _ = case(tmp_path, monkeypatch)
    ticks=[0]
    monkeypatch.setattr('sim_policy_inference.perf_counter_ns', lambda: ticks[0])
    class LiveCamera:
        def capture(self):
            elapsed=session.policy.binding.timing['max_observation_age_ns']
            ticks[0]+=elapsed;clock[0]+=elapsed/1e9
            session.observe(replace(session._snapshot,sequence=11,received_at=clock[0]))
            cameras[0]=replace(cameras[0],received_at_ns=int(clock[0]*1e9))
            return nullcontext(CapturedRGB(cameras[0],packet.rgb))
    checks=[]
    def live():
        assert not session._lock._is_owned()
        checks.append(ticks[0])
    proposed,result=infer_for_owner(engine,session,LiveCamera(),require_live=live)
    assert len(checks)>=3 and len(seen)==1 and not client.commands
    assert proposed.observed_at_ns==result.source.observed_at_ns==int(clock[0]*1e9)
    assert proposed.sequence==11 and proposed.camera_received_at_ns==(cameras[0].received_at_ns,)
    assert session.submit(proposed).accepted


@pytest.mark.parametrize('expires_during', ['capture','inference'])
def test_actor_budget_expiry_drops_input_or_computed_candidate(tmp_path, monkeypatch, expires_during):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch)
    expired=[False]
    if expires_during=='capture':
        original=session.capture_inference_input
        def capture(*args):
            result=original(*args);expired[0]=True;return result
        monkeypatch.setattr(session,'capture_inference_input',capture)
    else:
        import sim_policy_inference
        original=sim_policy_inference.infer_captured
        def compute(*args,**kwargs):
            result=original(*args,**kwargs);expired[0]=True;return result
        monkeypatch.setattr(sim_policy_inference,'infer_captured',compute)
    def live():
        assert not session._lock._is_owned()
        if expired[0]:raise TimeoutError('original actor deadline')
    with pytest.raises(TimeoutError,match='original actor deadline'):
        infer_for_owner(engine,session,packet,require_live=live)
    assert len(seen)==int(expires_during=='inference') and not client.commands


def test_install_precheck_allows_joint_intake_before_atomic_capture(tmp_path, monkeypatch):
    session, engine, packet, client, *_ = case(tmp_path, monkeypatch)
    original = InstalledPolicy.recheck
    delivered, workers, failures = threading.Event(), [], []
    first = True
    snapshot = replace(session._snapshot, sequence=11)

    def observe():
        try:
            session.observe(snapshot)
        except Exception as error:
            failures.append(error)
        finally:
            delivered.set()

    def recheck(policy):
        nonlocal first
        if policy is session.policy and first:
            first = False
            worker = threading.Thread(target=observe, daemon=True)
            workers.append(worker)
            worker.start()
            assert delivered.wait(1), 'installed verification blocked live joint intake'
            assert not failures
        return original(policy)

    monkeypatch.setattr(InstalledPolicy, 'recheck', recheck)
    try:
        candidate, result = infer_for_owner(engine, session, packet)
    finally:
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
    assert candidate.sequence == result.source.sequence == 11
    assert result.source.observed_at_ns == int(snapshot.received_at * 1e9)
    assert not client.commands


def test_install_tamper_after_precheck_is_rejected_at_capture(tmp_path, monkeypatch):
    session, engine, packet, client, _, _, _, seen, root = case(tmp_path, monkeypatch)
    original = InstalledPolicy.recheck
    first = True

    def recheck(policy):
        nonlocal first
        doc = original(policy)
        if policy is session.policy and first:
            first = False
            path = root / doc['files'][0]['path']
            path.write_bytes(path.read_bytes() + b'tampered after precheck')
        return doc

    monkeypatch.setattr(InstalledPolicy, 'recheck', recheck)
    with pytest.raises(ValueError, match='artifact file hash/size differs'):
        infer_for_owner(engine, session, packet)
    assert not seen and not client.commands


def test_live_capture_is_atomic_under_owner_lock_but_predict_is_outside(tmp_path, monkeypatch):
    session, engine, packet, client, *_ = case(tmp_path, monkeypatch)
    active = []
    class LiveCamera:
        @contextmanager
        def capture(self):
            assert session._lock._is_owned()
            active.append(True)
            try:
                yield packet
            finally:
                active.pop()
    predict=engine._predict
    def checked(observation):
        assert not active and not session._lock._is_owned()
        return predict(observation)
    engine._predict=checked
    proposed, _=infer_for_owner(engine,session,LiveCamera())
    assert session.submit(proposed).accepted and len(client.commands)==1


def test_valid_same_scope_renewal_during_compute_preserves_original_candidate(tmp_path, monkeypatch):
    session, engine, packet, client, clock, *_ = case(tmp_path, monkeypatch)
    original=session.lease
    predict=engine._predict
    def renewing(observation):
        actions=predict(observation)
        clock[0]+=.001
        session.renew(replace(original,issued_at_ns=int(clock[0]*1e9),
                              expires_at_ns=original.expires_at_ns+1_000_000))
        return actions
    engine._predict=renewing
    proposed,result=infer_for_owner(engine,session,packet)
    assert session.lease is not original
    assert proposed.lease_id==original.lease_id
    assert proposed.observed_at_ns==10_000_000_000
    assert result.source.camera_received_at_ns==10_000_000_000
    assert session.submit(proposed).accepted and len(client.commands)==1


@pytest.mark.parametrize('change', ['bytes', 'timestamp', 'identity'])
def test_replaced_capture_rejected_before_predict(tmp_path, monkeypatch, change):
    session, engine, packet, client, _, _, _, seen, _ = case(tmp_path, monkeypatch)
    if change == 'bytes':
        with pytest.raises(ValueError): session.capture_inference_input(b'\0'*192, packet.metadata)
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


def test_candidate_return_defers_install_admission_to_existing_owner(tmp_path, monkeypatch):
    session, engine, packet, client, _, _, _, seen, root = case(tmp_path, monkeypatch)
    predict=engine._predict
    def changed_install(observation):
        actions=predict(observation)
        (root/'policy/model.safetensors').write_bytes(b'changed after numerical inference')
        return actions
    engine._predict=changed_install
    proposed, result=infer_for_owner(engine, session, packet)
    assert len(seen)==1 and not client.commands
    assert proposed.observed_at_ns==result.source.observed_at_ns
    with pytest.raises(PermissionError):
        session.submit(proposed)
    assert session.hold_reason and not client.commands


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
    session, _, packet, *_ = case(tmp_path, monkeypatch)
    mutable = bytearray(packet.rgb)
    frozen = session.capture_inference_input(mutable, packet.metadata)
    mutable[0] ^= 255
    assert frozen.rgb == packet.rgb


@pytest.mark.parametrize('change', [dict(lease_id='other'),dict(issued_at_ns=9_999_999_999),
                                  dict(expires_at_ns=10_499_999_999)])
def test_lease_change_during_prediction_cannot_relabel_result(tmp_path, monkeypatch, change):
    session, engine, packet, client, *_ = case(tmp_path, monkeypatch)
    original = engine._predict
    def predict(obs):
        actions = original(obs)
        session._lease = replace(session.lease, **change)
        return actions
    engine._predict = predict
    with pytest.raises(ValueError, match='lease'): infer_for_owner(engine, session, packet)
    assert not client.commands


def test_completed_proposal_does_not_wait_for_another_owner_transaction(tmp_path, monkeypatch):
    session,engine,packet,client,*_=case(tmp_path,monkeypatch)
    locked,release,finished=threading.Event(),threading.Event(),threading.Event()
    workers=[];outcome=[]
    predict=engine._predict
    def hold_owner():
        with session._lock:
            locked.set()
            assert release.wait(3)
    def predicting(observation):
        actions=predict(observation)
        worker=threading.Thread(target=hold_owner,daemon=True)
        workers.append(worker);worker.start()
        assert locked.wait(1)
        return actions
    def infer():
        try:outcome.append(infer_for_owner(engine,session,packet))
        except Exception as error:outcome.append(error)
        finally:finished.set()
    engine._predict=predicting
    worker=threading.Thread(target=infer,daemon=True);worker.start()
    try:
        assert locked.wait(1)
        assert finished.wait(1), 'unadmitted proposal waited for the owner after numerical inference'
    finally:
        release.set();worker.join(2)
        for holder in workers:holder.join(2)
    assert not worker.is_alive() and all(not holder.is_alive() for holder in workers)
    assert len(outcome)==1 and not isinstance(outcome[0],Exception)
    candidate,result=outcome[0]
    assert candidate.observed_at_ns==result.source.observed_at_ns==10_000_000_000
    assert not client.commands
    assert session.submit(candidate).accepted


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


def test_common_dto_identity_preserves_learning_api():
    from act_inference import InferenceObservation, InferenceResult
    from rosy.contracts.learning import inference
    assert InferenceObservation is inference.InferenceObservation
    assert InferenceResult is inference.InferenceResult


def test_reentrant_camera_callback_lease_change_is_denied(tmp_path, monkeypatch):
    session, _, packet, client, *_ = case(tmp_path, monkeypatch)
    def replaced():
        session._lease = replace(session.lease, lease_id='new-lease')
        return (packet.metadata,)
    session._cameras = replaced
    with pytest.raises(PermissionError): session.capture_inference_input(packet.rgb, packet.metadata)
    assert session.hold_reason and not client.commands


def test_same_hash_wrong_rgb_dimensions_is_rejected(tmp_path, monkeypatch):
    session, _, packet, client, _, _, cameras, _, _ = case(tmp_path, monkeypatch)
    rgb = b'short'
    cameras[0] = replace(cameras[0], frame_sha256=hashlib.sha256(rgb).hexdigest())
    with pytest.raises(ValueError): session.capture_inference_input(rgb, cameras[0])
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
