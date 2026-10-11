"""Model PC offline calibration receipt; no provider, promotion or device access."""
import argparse
import json
from pathlib import Path
import sys

LIMIT = 16 * 1024 * 1024


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='frozen fit/evaluation/training/reviewed_profile JSON')
    parser.add_argument('--compare', action='store_true', help='compare 2-4 bundles on identical held-out truth')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'operations/decision/src'), str(root / 'contracts/foundation')]
    try:
        from rosy.decision.deliberation.calibration import evaluate_calibration
        with args.input.open('rb') as source:
            raw = source.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('CALIBRATION_INPUT_EXCEEDED')
        data = json.loads(raw)
        if args.compare:
            from rosy.decision.deliberation.evaluation.comparison import compare_calibrations
            artifact = compare_calibrations(data)
        else:
            if type(data) is not dict or set(data) != {'fit', 'evaluation', 'training', 'reviewed_profile'}:
                raise ValueError('INVALID_CALIBRATION_BUNDLE')
            artifact = evaluate_calibration(data['fit'], data['evaluation'],
                training=data['training'], reviewed_profile=data['reviewed_profile'])
        print(artifact.report_json)
        return 0 if artifact.report['state'] in {'PASS_OFFLINE_ONLY', 'PASS_COMPARISON_OFFLINE_ONLY'} else 1
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print('{"state":"HOLD","reason":"INVALID_CALIBRATION_INPUT","field_accepted":false}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
