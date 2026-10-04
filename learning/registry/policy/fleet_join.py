"""Offline Episode / D-18 Action receipt binding; grants no execution authority.

Usage: fleet_join.py <episode-manifest.json> <receipt.json> <new-export.json>
Input receipts must come from an independently acquired owner/Fleet export.
Hash verification proves preserved bytes, not receipt authenticity or task success.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'src/contracts/foundation')]

from core_common.protocol.schemas import DeviceActionReceipt  # noqa: E402
from rosy.contracts.learning import seal, validate_episode  # noqa: E402
from rosy.contracts.learning.omx import validate_profile as validate_omx  # noqa: E402
from rosy.contracts.learning.pinky import validate_profile as validate_pinky  # noqa: E402


def _profile(episode, root):
    validators = {'omx_demonstration_v1': validate_omx, 'pinky_recording_session_v1': validate_pinky}
    if episode['profile'] not in validators:
        raise ValueError('Episode profile provenance validator not implemented')
    validators[episode['profile']](episode, root=root)


def join(episode, receipt):
    """Bind only an unambiguous device action/attempt pair, preserving both outcomes."""
    episode = validate_episode(episode)
    wire = DeviceActionReceipt.model_validate(receipt).model_dump(mode='json')
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
    names = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id',
             'instance_id', 'request_digest', 'authority_epoch', 'dispatch_generation')
    return seal(dict(schema='rosy.learning-fleet-export/1', episode_revision=episode['revision'],
                     policy_revision=episode['revisions']['policy'],
                     environment=episode['environment'], status='unmatched' if reason else 'matched',
                     reason=reason, binding=None if reason else {name: wire[name] for name in names},
                     episode_outcome=episode['outcome'], receipt=wire,
                     verification='metadata_only', inputs=None))


def export(episode_file, receipt_file, output):
    """Validate source file closure, preserve input hashes, and never replace an export."""
    episode_file, receipt_file, output = map(Path, (episode_file, receipt_file, output))
    if output.resolve().drive.upper() == 'F:':
        raise ValueError('artifact output belongs on X:, not the source drive')
    episode_bytes, receipt_bytes = episode_file.read_bytes(), receipt_file.read_bytes()
    episode = json.loads(episode_bytes)
    validate_episode(episode, root=episode_file.parent)
    _profile(episode, episode_file.parent)
    result = join(episode, json.loads(receipt_bytes))
    if result['status'] == 'matched' and episode['profile'] == 'omx_demonstration_v1':
        preserved = [json.loads((episode_file.parent / ref['path']).read_text(encoding='utf-8'))
                     for ref in episode['sources'] if ref['path'].startswith('owner-receipts/')]
        names = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id', 'instance_id',
                 'request_digest', 'authority_epoch', 'dispatch_generation', 'journal_id')
        wire = result['receipt']
        if (not preserved or any(wire[name] != preserved[0][name] for name in names)
                or wire['driver_goal_id'] not in {item['driver_goal_id'] for item in preserved}):
            result.update(status='unmatched', reason='owner_receipt_identity_mismatch', binding=None)
        else:
            result['binding']['journal_id'] = wire['journal_id']
    result['inputs'] = dict(episode_manifest_sha256=hashlib.sha256(episode_bytes).hexdigest(),
                            receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest())
    result['verification'] = 'episode_file_hashes_and_receipt_schema'
    # Check again before publication: no silent source rewrite during the join.
    validate_episode(episode, root=episode_file.parent)
    _profile(episode, episode_file.parent)
    if episode_file.read_bytes() != episode_bytes or receipt_file.read_bytes() != receipt_bytes:
        raise ValueError('input changed during export')
    result = seal(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode', type=Path)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = export(args.episode, args.receipt, args.output)
    print(json.dumps(dict(revision=result['revision'], status=result['status'], reason=result['reason'])))


if __name__ == '__main__':
    main()
