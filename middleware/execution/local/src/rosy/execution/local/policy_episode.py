"""Publish same-execution evidence; no raw observation, inference or task grant."""
import hashlib
import json
import os
from pathlib import Path

from omx_adapter.policy_parent import encoded
from rosy.contracts.learning import seal
from rosy.contracts.learning.omx_execution import validate_profile
from .policy_parent import correlate_parent


def publish(parent, api, journal, command_id, output):
    output = Path(output).resolve()
    if output.drive.upper() == 'F:' or output.exists():
        raise ValueError('new artifact directory outside source drive required')
    receipt_bytes = parent.owner_receipt(api)
    receipt = json.loads(receipt_bytes)
    runner_receipt = {name: value for name, value in receipt.items() if name != 'journal_id'}
    proof = correlate_parent(parent, journal, command_id, encoded(runner_receipt))
    before = parent.snapshot()
    native = journal.read(command_id)
    source = journal.read_source(proof['source_revision'])
    if (hashlib.sha256(encoded(before)).hexdigest() != proof['parent_snapshot_sha256']
            or hashlib.sha256(encoded(native)).hexdigest() != proof['native_snapshot_sha256']
            or receipt['journal_id'] != before['journal_id']):
        raise PermissionError('correlated original inputs changed')
    metadata = dict(availability='metadata_only', raw_camera_bytes_available=False,
                    inference_consumption_verified=False, execution_authorized=False,
                    task_outcome='unknown')
    payloads = {'parent.json': encoded(before), 'native.json': encoded(native),
                'source-header.json': encoded(source['header']), 'proof.json': encoded(proof),
                'observation.json': encoded(dict(evidence=metadata, intent=native['intent'])),
                'owner-receipts/000000.json': receipt_bytes}
    payloads.update({'installed/'+name: raw for name, raw in source['payloads'].items()})
    refs = {name: dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            for name, raw in payloads.items()}
    lease = native['intent']['lease']
    policy = json.loads(source['payloads']['policy/policy-artifact.json'])
    action = {'SUCCEEDED': 'succeeded', 'FAILED': 'failed'}.get(receipt['state'], 'unknown')
    doc = seal(dict(schema='rosy.episode/1', profile='omx_policy_execution_v1',
        episode_id=lease['episode_id'], device=receipt['instance_id'], robot_type=policy['robot_type'],
        environment='sim', clock_domain='steady', task='policy_execution', skill=None,
        revisions=dict(policy=proof['policy_revision'], model=None,
                       calibration=native['intent']['command']['calibration_revision'],
                       camera_profile=policy['camera_profile_revision']),
        sources=list(refs.values()), streams=dict(observation=refs['observation.json'],
            action=refs['native.json'], events=refs['native.json']),
        correlations=dict(action_ids=[receipt['action_id']], attempt_ids=[receipt['attempt_id']]),
        status='incomplete', outcome=dict(task='unknown', action=action, judge='unknown',
                                        evidence=[refs['owner-receipts/000000.json'], refs['native.json']])) )
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        file = output/name
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    payload = (json.dumps(doc, ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode()
    pending = output/'.manifest.pending'
    with pending.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    # Validate every persisted payload once, after all pending writes. A second
    # full pass before the pending manifest cannot improve this final closure.
    validate_profile(doc, root=output)
    # This full reread is deliberately after every payload/manifest write.
    if (correlate_parent(parent, journal, command_id, encoded(runner_receipt)) != proof
            or parent.owner_receipt(api) != receipt_bytes):
        raise PermissionError('original inputs changed during publication')
    parent.validate()  # Final check follows stored proof and manifest work.
    os.link(pending, output/'manifest.json')  # Complete marker, never replaces.
    pending.unlink()
    return doc
