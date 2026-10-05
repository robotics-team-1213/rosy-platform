"""Existing offline Fleet metadata binding; no authentication or execution grant."""
import hashlib
import json

from .artifacts import seal, validate_episode

IDENTITY = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id',
            'instance_id', 'request_digest', 'authority_epoch', 'dispatch_generation')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def join_metadata(episode, wire):
    """Caller validates the receipt using the existing device protocol schema."""
    episode = validate_episode(episode)
    keys = episode['correlations']
    reason = None
    if not keys['action_ids'] or not keys['attempt_ids']:
        reason = 'missing_episode_correlations'
    elif len(keys['action_ids']) != 1 or len(keys['attempt_ids']) != 1:
        reason = 'ambiguous_episode_correlations'
    elif episode['device'] != wire['instance_id']:
        reason = 'instance_mismatch'
    elif keys['action_ids'][0] != wire['action_id'] or keys['attempt_ids'][0] != wire['attempt_id']:
        reason = 'action_attempt_mismatch'
    else:
        terminal = {'SUCCEEDED': 'succeeded', 'FAILED': 'failed'}
        recorded = episode['outcome']['action']
        if wire['state'] in terminal and recorded != 'unknown' and recorded != terminal[wire['state']]:
            reason = 'action_outcome_conflict'
    return seal(dict(schema='rosy.learning-fleet-export/1', episode_revision=episode['revision'],
                     policy_revision=episode['revisions']['policy'],
                     environment=episode['environment'], status='unmatched' if reason else 'matched',
                     reason=reason, binding=None if reason else {name: wire[name] for name in IDENTITY},
                     episode_outcome=episode['outcome'], receipt=wire,
                     verification='metadata_only', inputs=None))


def export_metadata(episode, wire, preserved, episode_bytes, receipt_bytes):
    """Bind already validated profile/receipt snapshots, preserving the existing wire."""
    result = join_metadata(episode, wire)
    if result['status'] == 'matched' and episode['profile'] in {
            'omx_demonstration_v1', 'omx_policy_execution_v1'}:
        if (not preserved or any(wire[name] != preserved[0][name] for name in IDENTITY + ('journal_id',))
                or wire['driver_goal_id'] not in {item['driver_goal_id'] for item in preserved}):
            result.update(status='unmatched', reason='owner_receipt_identity_mismatch', binding=None)
        else:
            result['binding']['journal_id'] = wire['journal_id']
        if (episode['profile'] == 'omx_policy_execution_v1' and result['status'] == 'matched'
                and encoded(wire) != encoded(preserved[0])):
            result.update(status='unmatched', reason='original_execution_receipt_mismatch', binding=None)
    result['inputs'] = dict(episode_manifest_sha256=hashlib.sha256(episode_bytes).hexdigest(),
                          receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest())
    result['verification'] = 'episode_file_hashes_and_receipt_schema'
    return seal(result)
