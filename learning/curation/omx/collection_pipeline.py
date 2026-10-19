"""Offline collection preparation and human-reviewed ACT training entrypoint."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'training/omx'))
import collection_intake as intake
import native_cycle as cycle
import native_review as native

PREPARED_FILES = ('intake-receipt.json', 'inspection.json', 'capture.json', 'environment.json', 'decisions.json')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(sessions, output, repo_id, *, completed_only=False, camera_references=None):
    """Write the inspected dataset and print exact review and next-command paths."""
    output = Path(output).resolve()
    receipt = intake.prepare(sessions, output, repo_id, completed_only=completed_only,
                             camera_references=camera_references)
    return dict(prepared_root=str(output), inspection=str(output/'inspection.json'),
                decisions=str(output/'decisions.json'), intake_receipt=str(output/'intake-receipt.json'),
                reader_verified=receipt['reader_verified'], review_required=True,
                next_command=dict(argv=[sys.executable, str(Path(__file__).resolve()), 'train', str(output),
                                        '--decisions', str(output/'decisions.json'),
                                        '--out', str(output.with_name(output.name+'-run'))]),
                uploaded=False, device_execution=False)


def train(prepared, decisions, output, *, steps=100, batch_size=8, device='cpu'):
    """Preflight all review decisions, then preserve and compose existing split/train receipts."""
    prepared, decisions = Path(prepared).resolve(), Path(decisions).resolve()
    output = native._new_output(output, prepared)
    if (type(steps) is not int or steps < 1 or type(batch_size) is not int or batch_size < 1
            or device not in ('cpu', 'cuda')):
        raise ValueError('positive training budgets and cpu/cuda device are required')
    originals = {name: (prepared/name).read_bytes() for name in PREPARED_FILES}
    intake_receipt = json.loads(originals['intake-receipt.json'])
    if intake_receipt.get('reader_verified') is not True or intake_receipt.get('fixture_only') is True:
        raise ValueError('verified production collection intake is required')
    report = json.loads(originals['inspection.json'])
    decision_bytes = decisions.read_bytes()
    reviewed = json.loads(decision_bytes)
    # This gate runs before creating output or invoking any dataset writer/trainer.
    native.reviewed_splits(report, reviewed)
    output.mkdir(parents=True)
    evidence = output/'prepared-evidence'
    evidence.mkdir()
    for name, raw in originals.items():
        (evidence/name).write_bytes(raw)
    (output/'reviewed-decisions.json').write_bytes(decision_bytes)
    splits, training = output/'splits', output/'training'
    native.split_reviewed(prepared, report, reviewed, splits)
    cycle.run_cycle(splits, training, steps=steps, batch_size=batch_size, device=device)
    if (any((prepared/name).read_bytes() != raw for name, raw in originals.items())
            or decisions.read_bytes() != decision_bytes):
        raise ValueError('prepared evidence or human decisions changed during training')
    receipt = dict(schema='rosy.omx-collection-pipeline.v1', offline_only=True,
                   prepared_root=str(prepared), decisions_path=str(decisions),
                   prepared_files={name: _hash(raw) for name, raw in originals.items()},
                   decisions_sha256=_hash(decision_bytes),
                   split_receipt_sha256=_hash((splits/'split-receipt.json').read_bytes()),
                   cycle_receipt_sha256=_hash((training/'cycle-receipt.json').read_bytes()),
                   splits=str(splits), training=str(training), steps=steps, batch_size=batch_size,
                   device=device, uploaded=False, device_execution=False, promotion=False)
    native.write_json(output/'pipeline-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('sessions', nargs='+', type=Path)
    preparation.add_argument('--out', type=Path, required=True)
    preparation.add_argument('--repo-id', required=True)
    preparation.add_argument('--completed-only', action='store_true')
    preparation.add_argument('--camera-reference', action='append', default=[], metavar='ROLE=PATH',
                             help='D-792 camera setup reference JSON per camera role; adds shadow checks')
    training = commands.add_parser('train')
    training.add_argument('prepared', type=Path)
    training.add_argument('--decisions', type=Path, required=True)
    training.add_argument('--out', type=Path, required=True)
    training.add_argument('--steps', type=int, default=100)
    training.add_argument('--batch-size', type=int, default=8)
    training.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.sessions, args.out, args.repo_id, completed_only=args.completed_only,
                             camera_references=intake.camera_references(args.camera_reference))
        else:
            result = train(args.prepared, args.decisions, args.out, steps=args.steps,
                           batch_size=args.batch_size, device=args.device)
    except (ValueError, OSError, ImportError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
