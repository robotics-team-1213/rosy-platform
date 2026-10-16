"""Rehearse, preflight or collect OMX sessions. Hardware always requires explicit accepted inputs."""
import argparse
import json
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'middleware/devices/omx/adapter'))
sys.path.insert(0, str(ROOT/'contracts/foundation'))
from collection_profile import validate_profile, validate_teacher
from collection_session import run_session
from collection_store import save


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    rehearsal = commands.add_parser('rehearsal-suite')
    rehearsal.add_argument('--out', type=Path, required=True)
    for name in ('check', 'preflight', 'collect'):
        sub = commands.add_parser(name)
        sub.add_argument('--profile', type=Path, required=True)
        sub.add_argument('--teacher', type=Path, required=True)
        sub.add_argument('--acceptance', type=Path)
        sub.add_argument('--out', type=Path, required=True)
        if name == 'collect':
            sub.add_argument('--episodes', type=int, default=1)
    args = parser.parse_args(argv)
    backend = None
    try:
        if args.out.exists():
            raise ValueError('output exists; choose a new directory')
        if args.command == 'rehearsal-suite':
            from collection_rehearsal import profile, teacher, RehearsalBackend
            args.out.mkdir(parents=True)
            rows = []
            for fault in ('none', 'dark', 'disconnect', 'stale_reference', 'reject', 'terminal_failure'):
                fake = RehearsalBackend(profile(), fault=fault)
                result = run_session(profile(), teacher(), args.out/fault, fake)
                complete = bool(result['episodes']) and result['episodes'][0]['complete']
                rows.append(dict(fault=fault, correct=complete == (fault == 'none') and fake.stopped,
                                 hardware_connections=fake.hardware_connections,
                                 raw_manifest=str(args.out/fault/'manifest.json')))
            report = dict(scope='software_rehearsal_only', checks=rows,
                          passed=all(r['correct'] and r['hardware_connections'] == 0 for r in rows),
                          physical_acceptance=False, real_demonstrations=0)
            save(args.out/'rehearsal.json', report)
            print(json.dumps(report))
            return 0 if report['passed'] else 2
        profile, teacher = load(args.profile), load(args.teacher)
        acceptance = load(args.acceptance) if args.acceptance else None
        validate_profile(profile, mode='hardware', acceptance=acceptance, teacher=teacher)
        validate_teacher(teacher, profile)
        if args.command == 'check':
            args.out.mkdir(parents=True)
            report = dict(config_valid=True, device_connected=False, motion_admitted=False)
            save(args.out/'check.json', report)
            print(json.dumps(report))
            return 0
        # Imports and construction are after static admission; check/rehearsal never import rclpy.
        from collection_ros import RosBackend
        def interrupt(*_):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, interrupt)
        backend = RosBackend(profile, acceptance, teacher)
        sample = backend.ready()
        if args.command == 'preflight':
            args.out.mkdir(parents=True)
            report = dict(ready=True, goals_submitted=0, motion_admitted=False,
                          environment_run_id=sample['environment']['run_id'])
            save(args.out/'preflight.json', report)
            print(json.dumps(report))
            return 0
        result = run_session(profile, teacher, args.out, backend, episodes=args.episodes)
        print(json.dumps(dict(manifest=str(args.out/'manifest.json'), episodes=result['episodes'],
                              stop=result['stop'], task_success=None)))
        return 0 if result['episodes'] and all(e['complete'] for e in result['episodes']) else 2
    except (Exception, KeyboardInterrupt) as exc:
        report = dict(refused=True, error=f'{type(exc).__name__}: {exc}', physical_acceptance=False)
        if not args.out.exists():
            args.out.mkdir(parents=True)
            save(args.out/'blocked.json', report)
        print(json.dumps(report), file=sys.stderr)
        return 2
    finally:
        if backend is not None:
            backend.close()


if __name__ == '__main__':
    raise SystemExit(main())
