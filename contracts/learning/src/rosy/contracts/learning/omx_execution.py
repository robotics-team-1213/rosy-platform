"""Same-execution file provenance, not live receipt authentication or training GT."""
import hashlib
import json
from pathlib import Path

from .artifacts import validate_episode, validate_policy
from .omx_execution_intent import intent_semantics, native_semantics

IDENTITY = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id', 'instance_id',
            'request_digest', 'authority_epoch', 'dispatch_generation')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def _validate_profile(doc, *, root):
    # Validate reference metadata first; capture and hash each source once
    # below. Streams/outcomes must then match those exact captured references.
    value = validate_episode(doc)
    if value['profile'] != 'omx_policy_execution_v1':
        raise ValueError('OMX execution profile required')
    root = Path(root).resolve()
    refs = {ref['path']: ref for ref in value['sources']}
    required = {'parent.json', 'native.json', 'source-header.json', 'proof.json',
                'observation.json', 'owner-receipts/000000.json'}
    if not required <= set(refs) or len(refs) != len(value['sources']):
        raise ValueError('exact original execution references required')
    payloads = {}
    for name in refs:
        path = root/name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('execution source symlink rejected')
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError('execution source escapes root or is missing')
        payloads[name] = path.read_bytes()
        if len(payloads[name]) != refs[name]['bytes'] or sha(payloads[name]) != refs[name]['sha256']:
            raise ValueError('captured original execution source changed')
    def read(name):
        return json.loads(payloads[name])
    parent, native, header, proof, receipt, observation = map(read, (
        'parent.json', 'native.json', 'source-header.json', 'proof.json',
        'owner-receipts/000000.json', 'observation.json'))
    if (set(refs) != required | {'installed/'+ref['path'] for ref in header['files']}
            or len(header['files']) != len(refs)-len(required)):
        raise ValueError('original installation file coverage differs')
    for ref in header['files']:
        name = 'installed/'+ref['path']
        if refs[name] != dict(ref, path=name):
            raise ValueError('original installation byte closure differs')
    policy = validate_policy(read('installed/policy/policy-artifact.json'))
    for ref in policy['files'] + [policy['normalization']] + policy['evaluations']:
        if refs.get('installed/policy/'+ref['path']) != dict(ref, path='installed/policy/'+ref['path']):
            raise ValueError('original model/normalization/eval closure differs')
    intent, events = native['intent'], native['events']
    native_semantics(events)
    binding,config=read('installed/installed/binding.json'),read('installed/owner/config.json')
    if policy['owner'] != dict(kind='omx_local_controller',
            controller_revision='sha256:'+sha(payloads['installed/owner/controller.py']),
            envelope_revision='sha256:'+sha(payloads['installed/owner/config.json'])):
        raise ValueError('original controller/envelope bytes differ')
    intent_semantics(intent,policy,binding,config)
    lease, candidate, command = intent['lease'], intent['candidate'], intent['command']
    identity = {name: receipt[name] for name in IDENTITY}
    for name in ('authority_epoch', 'dispatch_generation', 'journal_event_id'):
        if type(receipt[name]) is not int or receipt[name] < (1 if name == 'journal_event_id' else 0):
            raise ValueError('exact receipt integer required')
    if (encoded(lease['identity']) != encoded(identity)
            or any(encoded(parent['action']['request']['payload'][name]) != encoded(receipt[name])
                   for name in IDENTITY)
            or not isinstance(receipt['journal_id'], str) or not receipt['journal_id'].strip()
            or receipt['journal_id'] != parent['journal_id']
            or receipt['state'] != parent['action']['state']
            or receipt['journal_event_id'] != parent['action']['journal_event_id']
            or receipt['journal_event_id'] != parent['events'][-1]['event_id']
            or receipt['observed_at'] != parent['action']['updated_at']):
        raise ValueError('original parent/lease/receipt identity differs')
    if (header['policy_revision'] != policy['revision']
            or header['environment'] != 'sim' or policy['environment'] != 'sim'
            or intent['policy_revision'] != policy['revision']
            or lease['policy_revision'] != policy['revision']
            or candidate['policy_revision'] != policy['revision']
            or candidate['lease_id'] != lease['lease_id']
            or candidate['episode_id'] != lease['episode_id']
            or command['session_id'] != lease['owner_session_id']
            or command['owner'] != 'learned_policy'
            or command['source_state_sequence'] != candidate['sequence']
            or command['joint_names'] != policy['joint_names']
            or [command['positions'][name] for name in command['joint_names']] != candidate['positions']):
        raise ValueError('original policy/intent scope differs')
    goal = native['driver_goal_id']
    if (not isinstance(goal, str) or not goal or goal == command['command_id'] or not events
            or events[0]['kind'] != 'GOAL_ACCEPTED'
            or any(type(event['sequence']) is not int or event['sequence'] != i+1
                   or event['goal_id'] != goal or event['command_id'] != command['command_id']
                   or event['phase_id'] != command['phase_id'] for i, event in enumerate(events))
            or any(event['kind'] in {'GOAL_ACCEPTED', 'GOAL_REJECTED', 'GOAL_ACCEPTANCE_UNKNOWN'}
                   for event in events[1:])
            or any(event['kind'] in {'TERMINAL_RESULT', 'TERMINAL_UNKNOWN'} for event in events[:-1])
            or any(a['observed_at_monotonic_s'] > b['observed_at_monotonic_s'] for a,b in zip(events,events[1:]))):
        raise ValueError('original native callbacks differ')
    if command['phase_id'] is None:
        if goal != receipt['driver_goal_id']:
            raise ValueError('original accepted parent goal differs')
    elif len([phase for phase in parent['phases'] if phase['phase_id'] == command['phase_id']
              and phase['driver_goal_id'] == goal]) != 1:
        raise ValueError('original accepted phase goal differs')
    if receipt['state'] == 'SUCCEEDED' and not (
            events[-1]['kind'] == 'TERMINAL_RESULT' and type(events[-1]['status']) is int
            and events[-1]['status'] == 4 and type(events[-1]['result_code']) is int
            and events[-1]['result_code'] == 0):
        raise ValueError('Action success lacks original native success')
    stripped = {name: item for name,item in receipt.items() if name != 'journal_id'}
    unsigned = {name: item for name,item in proof.items() if name != 'revision'}
    if (sha(encoded(unsigned)) != proof['revision']
            or sha(encoded(parent)) != proof['parent_snapshot_sha256']
            or sha(encoded(native)) != proof['native_snapshot_sha256']
            or sha(encoded(header)) != intent['source_revision']
            or proof['source_revision'] != intent['source_revision']
            or encoded(json.loads(proof['receipt_json'])) != encoded(stripped)
            or sha(proof['receipt_json'].encode()) != proof['receipt_sha256']
            or proof['command_id'] != command['command_id'] or proof['driver_goal_id'] != goal
            or proof['policy_revision'] != policy['revision'] or proof['request_digest'] != receipt['request_digest']
            or proof['action_state'] != receipt['state'] or proof['task_outcome'] != 'unknown'
            or any(proof[name] is not False for name in (
                'execution_authorized','episode_fleet_qualified','inference_consumption_verified'))):
        raise ValueError('original correlation proof differs')
    expected_observation = dict(evidence=dict(availability='metadata_only', raw_camera_bytes_available=False,
        inference_consumption_verified=False, execution_authorized=False, task_outcome='unknown'), intent=intent)
    if encoded(observation) != encoded(expected_observation):
        raise ValueError('metadata-only observations must not become inference or raw camera evidence')
    expected = dict(episode_id=lease['episode_id'], device=receipt['instance_id'], robot_type=policy['robot_type'],
        environment='sim', clock_domain='steady', task='policy_execution', skill=None, status='incomplete',
        revisions=dict(policy=policy['revision'], model=None, calibration=command['calibration_revision'],
                       camera_profile=policy['camera_profile_revision']),
        streams=dict(observation=refs['observation.json'],action=refs['native.json'],events=refs['native.json']),
        correlations=dict(action_ids=[receipt['action_id']],attempt_ids=[receipt['attempt_id']]),
        outcome=dict(task='unknown',action={'SUCCEEDED':'succeeded','FAILED':'failed'}.get(receipt['state'],'unknown'),
                     judge='unknown',evidence=[refs['owner-receipts/000000.json'],refs['native.json']]))
    if any(encoded(value[name]) != encoded(item) for name,item in expected.items()):
        raise ValueError('Episode differs from original execution provenance')
    return dict(receipt=receipt, native=native, policy=policy, parent=parent)


def validate_profile(doc, *, root):
    try:
        return _validate_profile(doc,root=root)
    except (KeyError,TypeError,IndexError,AttributeError,OverflowError) as error:
        raise ValueError('malformed original execution body') from error
