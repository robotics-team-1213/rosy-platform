"""Private policy/Action correlation only; does not grant learned task semantics."""
import hashlib
import json

from core_common.protocol.schemas import DeviceActionReceipt
from omx_adapter.policy_parent import _ParentCapability, _MINTED, encoded, projection
from omx_adapter.command_owner import ArmCommandConfig, TrajectoryCommand
from omx_adapter.manipulation_plan import JointTrajectoryPoint
from omx_adapter.ros_goal_contract import RosGoalEvent
from rosy.contracts.learning import validate_policy
from .policy_journal import PolicyExecutionJournal
from .policy_install import InstallBinding
from .omx_policy import PolicyCandidate, PolicyLease
from rosy.contracts.skill import AttemptIdentity


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _source(source, revision, policy_revision):
    header, payloads = source['header'], source['payloads']
    if _sha(encoded(header)) != revision or header['policy_revision'] != policy_revision:
        raise ValueError('original source revision differs')
    refs = header['files']
    if len(refs) != len(payloads) or {ref['path'] for ref in refs} != set(payloads):
        raise ValueError('original source coverage differs')
    for ref in refs:
        raw = payloads[ref['path']]
        if type(raw) is not bytes or len(raw) != ref['bytes'] or _sha(raw) != ref['sha256']:
            raise ValueError('original source bytes differ')
    doc = validate_policy(json.loads(payloads['policy/policy-artifact.json']))
    binding = InstallBinding(**json.loads(payloads['installed/binding.json']))
    config = ArmCommandConfig(**json.loads(payloads['owner/config.json']))
    if (doc['revision'] != policy_revision or doc['owner'] != header['owner']
            or doc['environment'] != 'sim' or header['environment'] != 'sim'
            or binding.policy_revision != policy_revision or encoded(binding.owner) != encoded(doc['owner'])
            or any(doc[name] != getattr(binding, name) for name in (
                'profile', 'robot_type', 'environment', 'device_profile_revision', 'camera_profile_revision'))
            or encoded(binding.cameras) != encoded(doc['cameras'])
            or binding.normalization_sha256 != doc['normalization']['sha256']
            or tuple(doc['action']['names']) != binding.action_names
            or tuple(doc['joint_names']) != config.joint_names or not config.enabled
            or 'learned_policy' not in config.allowed_owners
            or doc['timing']['period_ns'] != binding.timing['period_ns']
            or any(doc['timing'][name] > budget for name, budget in binding.timing.items())):
        raise ValueError('original policy manifest/installation differs')
    if len(binding.action_limits) != len(doc['action']['limits']):
        raise ValueError('original installed action dimensions differ')
    for name, actual, admitted in zip(binding.action_names, doc['action']['limits'], binding.action_limits):
        owner_limits = config.position_limits[name]
        if not owner_limits[0] <= admitted[0] <= actual[0] < actual[1] <= admitted[1] <= owner_limits[1]:
            raise ValueError('original action exceeds installed or owner envelope')
    if doc['owner'] != dict(kind='omx_local_controller',
            controller_revision='sha256:' + _sha(payloads['owner/controller.py']),
            envelope_revision='sha256:' + _sha(payloads['owner/config.json'])):
        raise ValueError('original owner/controller envelope differs')
    for ref in doc['files'] + [doc['normalization']] + doc['evaluations']:
        raw = payloads['policy/' + ref['path']]
        if len(raw) != ref['bytes'] or _sha(raw) != ref['sha256']:
            raise ValueError('original model/normalization/eval file differs')
    return doc, config


def _intent(intent, command_id, doc, config):
    lease = PolicyLease(**dict(intent['lease'], identity=AttemptIdentity(**intent['lease']['identity'])))
    candidate = PolicyCandidate(**intent['candidate'])
    raw_command = dict(intent['command'])
    if raw_command.get('trajectory_points') is not None:
        raw_command['trajectory_points'] = tuple(JointTrajectoryPoint(**point)
                                                for point in raw_command['trajectory_points'])
    command = TrajectoryCommand(**raw_command)
    if ((candidate.lease_id, candidate.episode_id, candidate.policy_revision) !=
            (lease.lease_id, lease.episode_id, lease.policy_revision)
            or command.command_id != command_id or command.owner != 'learned_policy'
            or command.session_id != lease.owner_session_id
            or command.source_state_sequence != candidate.sequence
            or command.joint_names != config.joint_names
            or command.calibration_revision != config.calibration_revision
            or (command.workcell_id, command.instance_id) != (config.workcell_id, config.instance_id)
            or tuple(command.positions[name] for name in command.joint_names) != candidate.positions
            or any(not low <= value <= high for value, (low, high) in
                   zip(candidate.positions, doc['action']['limits']))):
        raise ValueError('original candidate/command/install scope differs')


def correlate_parent(parent, journal, command_id, receipt_bytes):
    """Capture current coherent readbacks with final freshness/race checks.

    The supplied receipt must be the exact current owner GET projection, not a
    historical response. Input bytes are hashed and preserved in the return.
    No wire journal_id is filled from a path/digest. Episode/Fleet qualification
    awaits a separately defined provenance profile and lawful task semantics.
    """
    return _capture_parent(parent, journal, command_id, receipt_bytes)[0]


def _capture_parent(parent, journal, command_id, receipt_bytes):
    """Private checked inputs for serialization, with the same final guards.

    The returned snapshots are those hashed into the proof, not a permission
    or a cache usable for another execution. Publication must still reread
    all original inputs and authority after writing its pending artifact.
    """
    if (not isinstance(parent, _ParentCapability) or parent not in _MINTED
            or not isinstance(journal, PolicyExecutionJournal)):
        raise PermissionError('actual runner capability and native journal required')
    if type(receipt_bytes) is not bytes:
        raise ValueError('original receipt bytes required')
    before = parent.snapshot()
    expected = projection(before)
    receipt = json.loads(receipt_bytes)
    DeviceActionReceipt.model_validate(receipt)
    if encoded(receipt) != encoded(expected):
        raise ValueError('receipt differs from current authoritative parent snapshot')
    native = journal.read(command_id)
    intent = native['intent']
    lease = intent['lease']
    names = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id', 'instance_id',
             'request_digest', 'authority_epoch', 'dispatch_generation')
    if encoded(lease['identity']) != encoded({name: receipt[name] for name in names}):
        raise PermissionError('policy lease is not bound to the admitted parent')
    if (intent['policy_revision'] != lease['policy_revision']
            or intent['candidate']['policy_revision'] != lease['policy_revision']
            or intent['command']['command_id'] != command_id
            or intent['command']['session_id'] != lease['owner_session_id']):
        raise ValueError('original policy intent scope differs')
    revision = intent.get('source_revision')
    if not revision:
        raise ValueError('installed original source snapshot required')
    source = journal.read_source(revision)
    doc, config = _source(source, revision, lease['policy_revision'])
    _intent(intent, command_id, doc, config)
    events = [RosGoalEvent(**event) for event in native['events']]
    goal = native['driver_goal_id']
    if (not events or events[0].kind != 'GOAL_ACCEPTED' or goal is None or goal == command_id
            or any(event.command_id != command_id or event.goal_id != goal
                   or event.phase_id != intent['command']['phase_id'] for event in events)
            or [event.sequence for event in events] != list(range(1, len(events) + 1))
            or any(event.kind in {'GOAL_ACCEPTED', 'GOAL_REJECTED', 'GOAL_ACCEPTANCE_UNKNOWN'}
                   for event in events[1:])
            or any(event.kind in {'TERMINAL_RESULT', 'TERMINAL_UNKNOWN'} for event in events[:-1])
            or any(a.observed_at_monotonic_s > b.observed_at_monotonic_s for a, b in zip(events, events[1:]))):
        raise ValueError('original accepted native goal facts differ')
    phase_id = intent['command']['phase_id']
    if phase_id is None:
        if goal != receipt['driver_goal_id']:
            raise ValueError('native goal differs from the parent accepted goal')
    else:
        matching = [phase for phase in before['phases'] if phase['phase_id'] == phase_id
                    and phase['driver_goal_id'] == goal]
        if len(matching) != 1:
            raise ValueError('native goal lacks the original accepted parent phase')
    if receipt['state'] == 'SUCCEEDED' and not (
            events[-1].kind == 'TERMINAL_RESULT' and events[-1].status == 4
            and events[-1].result_code == 0):
        raise ValueError('Action success conflicts with native terminal facts')
    if encoded(journal.read(command_id)) != encoded(native):
        raise PermissionError('native facts changed during correlation')
    current_source = journal.read_source(revision)
    _source(current_source, revision, lease['policy_revision'])
    if current_source != source:
        raise PermissionError('original source changed during correlation')
    after = parent.snapshot()
    if encoded(after) != encoded(before):
        raise PermissionError('parent or native facts changed during correlation')
    result = dict(scope='private_current_parent_correlation', command_id=command_id,
        driver_goal_id=goal, policy_revision=lease['policy_revision'], source_revision=revision,
        request_digest=receipt['request_digest'], action_state=receipt['state'], task_outcome='unknown',
        parent_snapshot_sha256=_sha(encoded(before)), native_snapshot_sha256=_sha(encoded(native)),
        receipt_sha256=_sha(receipt_bytes), receipt_json=receipt_bytes.decode('utf-8'),
        execution_authorized=False, episode_fleet_qualified=False,
        inference_consumption_verified=False)
    result['revision'] = _sha(encoded(result))
    parent.validate()  # LAST: after all slow proof reads, hashing and JSON work.
    return result, before, native, source
