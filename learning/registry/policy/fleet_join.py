"""Offline Episode / D-18 Action receipt binding; grants no execution authority.

Usage: fleet_join.py <episode-manifest.json> <receipt.json> <new-export.json>
Input receipts must come from an independently acquired owner/Fleet export.
Hash verification proves preserved bytes, not receipt authenticity or task success.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'contracts/foundation')]

from core_common.protocol.schemas import DeviceActionReceipt  # noqa: E402
from rosy.contracts.learning import validate_episode  # noqa: E402
from rosy.contracts.learning.fleet_export import join_metadata, export_metadata  # noqa: E402
from rosy.contracts.learning.omx import validate_profile as validate_omx  # noqa: E402
from rosy.contracts.learning.pinky import validate_profile as validate_pinky  # noqa: E402
from rosy.contracts.learning.omx_execution import validate_profile as validate_execution  # noqa: E402


def _profile(episode, root):
    validators = {'omx_demonstration_v1': validate_omx, 'pinky_recording_session_v1': validate_pinky,
                  'omx_policy_execution_v1': validate_execution}
    if episode['profile'] not in validators:
        raise ValueError('Episode profile provenance validator not implemented')
    validators[episode['profile']](episode, root=root)


def join(episode, receipt):
    """Bind only an unambiguous device action/attempt pair, preserving both outcomes."""
    wire = DeviceActionReceipt.model_validate(receipt).model_dump(mode='json')
    return join_metadata(episode, wire)


def export(episode_file, receipt_file, output):
    """Validate source file closure, preserve input hashes, and never replace an export."""
    episode_file, receipt_file, output = map(Path, (episode_file, receipt_file, output))
    if output.resolve().drive.upper() == 'F:':
        raise ValueError('artifact output belongs on X:, not the source drive')
    episode_bytes, receipt_bytes = episode_file.read_bytes(), receipt_file.read_bytes()
    episode = json.loads(episode_bytes)
    validate_episode(episode, root=episode_file.parent)
    _profile(episode, episode_file.parent)
    wire = DeviceActionReceipt.model_validate(json.loads(receipt_bytes)).model_dump(mode='json')
    preserved = [DeviceActionReceipt.model_validate(json.loads(
        (episode_file.parent / ref['path']).read_bytes())).model_dump(mode='json')
        for ref in episode['sources'] if ref['path'].startswith('owner-receipts/')]
    result = export_metadata(episode, wire, preserved, episode_bytes, receipt_bytes)
    payload = (json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.' + output.name + '-',
                                         suffix='.pending', delete=False) as stream:
            staged = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Validate after storage I/O as well: a slow write cannot hide input changes.
        validate_episode(episode, root=episode_file.parent)
        _profile(episode, episode_file.parent)
        if episode_file.read_bytes() != episode_bytes or receipt_file.read_bytes() != receipt_bytes:
            raise ValueError('input changed during export')
        # Atomic same-directory publication, without replacing another owner's result.
        os.link(staged, output)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
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
