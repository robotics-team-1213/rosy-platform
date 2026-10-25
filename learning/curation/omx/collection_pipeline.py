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
import experiment_native
from experiment_io import read_json

PREPARED_FILES = ('intake-receipt.json', 'inspection.json', 'capture.json', 'environment.json', 'decisions.json')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(sessions, output, repo_id, *, completed_only=False):
    """Write the inspected dataset and print exact review and next-command paths."""
    output = Path(output).resolve()
    receipt = intake.prepare(sessions, output, repo_id, completed_only=completed_only)
    return dict(prepared_root=str(output), inspection=str(output/'inspection.json'),
                decisions=str(output/'decisions.json'), intake_receipt=str(output/'intake-receipt.json'),
                reader_verified=receipt['reader_verified'], review_required=True,
                next_command=dict(argv=[sys.executable, str(Path(__file__).resolve()), 'train', str(output),
                                        '--decisions', str(output/'decisions.json'),
                                        '--out', str(output.with_name(output.name+'-run'))]),
                uploaded=False, device_execution=False)


def _review_inputs(prepared, decisions):
    originals = {name: (prepared/name).read_bytes() for name in PREPARED_FILES}
    return _validate_review_inputs(originals, decisions.read_bytes())


def _validate_review_inputs(originals, decision_bytes):
    intake_receipt = json.loads(originals['intake-receipt.json'])
    if intake_receipt.get('reader_verified') is not True or intake_receipt.get('fixture_only') is True:
        raise ValueError('verified production collection intake is required')
    report = json.loads(originals['inspection.json'])
    reviewed = json.loads(decision_bytes)
    # This gate runs before creating output or invoking any dataset writer/trainer.
    native.reviewed_splits(report, reviewed)
    return originals, report, decision_bytes, reviewed


def train(prepared, decisions, output, *, steps=100, batch_size=8, device='cpu'):
    """Preflight all review decisions, then preserve and compose existing split/train receipts."""
    prepared, decisions = Path(prepared).resolve(), Path(decisions).resolve()
    output = native._new_output(output, prepared)
    if (type(steps) is not int or steps < 1 or type(batch_size) is not int or batch_size < 1
            or device not in ('cpu', 'cuda')):
        raise ValueError('positive training budgets and cpu/cuda device are required')
    originals, report, decision_bytes, reviewed = _review_inputs(prepared, decisions)
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


def export_experiment(prepared, decisions, profile, output):
    """Reviewed intake -> sealed native splits -> uploadable ACT arrays, without training."""
    prepared, decisions, profile = (Path(value).resolve() for value in (prepared, decisions, profile))
    output = native._new_output(output, prepared)
    originals, report, decision_bytes, reviewed = _review_inputs(prepared, decisions)
    profile_bytes = profile.read_bytes()
    profile_document = read_json(profile)
    if profile.read_bytes() != profile_bytes:
        raise ValueError('profile changed during validation')
    output.mkdir(parents=True)
    evidence = output/'prepared-evidence'
    evidence.mkdir()
    for name, raw in originals.items():
        (evidence/name).write_bytes(raw)
    (output/'reviewed-decisions.json').write_bytes(decision_bytes)
    (output/'profile.json').write_bytes(profile_bytes)
    splits, dataset = output/'splits', output/'dataset'
    native.split_reviewed(prepared, report, reviewed, splits)
    converted = experiment_native.convert_native(splits, dataset, profile=profile_document)
    if (any((prepared/name).read_bytes() != raw for name, raw in originals.items())
            or decisions.read_bytes() != decision_bytes or profile.read_bytes() != profile_bytes):
        raise ValueError('prepared evidence, human decisions or profile changed during export')
    receipt = dict(schema='rosy.omx-experiment-export/1', dataset_root=str(dataset),
                   dataset_revision=converted['dataset_revision'], prepared_root=str(prepared),
                   prepared_files={name: _hash(raw) for name, raw in originals.items()},
                   decisions_sha256=_hash(decision_bytes), profile_sha256=_hash(profile_bytes),
                   split_receipt_sha256=_hash((splits/'split-receipt.json').read_bytes()),
                   conversion_receipt_sha256=_hash((dataset/'conversion-receipt.json').read_bytes()),
                   act_only=True, uploaded=False, device_execution=False, promotion=False)
    native.write_json(output/'experiment-export-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('sessions', nargs='+', type=Path)
    preparation.add_argument('--out', type=Path, required=True)
    preparation.add_argument('--repo-id', required=True)
    preparation.add_argument('--completed-only', action='store_true')
    native_prep = commands.add_parser('prepare-native', help='sealed leader or replay-teacher recordings to a prepared intake (D-848)')
    native_prep.add_argument('collections', nargs='+', type=Path)
    native_prep.add_argument('--out', type=Path, required=True)
    native_prep.add_argument('--repo-id', required=True)
    native_prep.add_argument('--rig-revision', help='scripted_teacher only: the bench layout the operator names')
    native_prep.add_argument('--calibration-revision', help='scripted_teacher only: the calibration the operator names')
    training = commands.add_parser('train')
    training.add_argument('prepared', type=Path)
    training.add_argument('--decisions', type=Path, required=True)
    training.add_argument('--out', type=Path, required=True)
    training.add_argument('--steps', type=int, default=100)
    training.add_argument('--batch-size', type=int, default=8)
    training.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    export = commands.add_parser('export-experiment', help='reviewed intake to Learning upload folder')
    export.add_argument('prepared', type=Path)
    export.add_argument('--decisions', type=Path, required=True)
    export.add_argument('--profile', type=Path, required=True)
    export.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.sessions, args.out, args.repo_id, completed_only=args.completed_only)
        elif args.command == 'prepare-native':
            receipt = intake.prepare_native(args.collections, args.out, args.repo_id,
                                            rig_revision=args.rig_revision,
                                            calibration_revision=args.calibration_revision)
            result = dict(prepared_root=str(args.out.resolve()), episodes=len(receipt['episodes']),
                          reader_verified=receipt['reader_verified'], review_required=True,
                          uploaded=False, device_execution=False)
        elif args.command == 'export-experiment':
            result = export_experiment(args.prepared, args.decisions, args.profile, args.out)
        else:
            result = train(args.prepared, args.decisions, args.out, steps=args.steps,
                           batch_size=args.batch_size, device=args.device)
    except (ValueError, OSError, ImportError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
