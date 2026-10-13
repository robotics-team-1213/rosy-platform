"""Automatic stationary camera calibration; approved SSH, no drive or promotion."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def ssh_command(alias):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', alias):
        raise ValueError('Use an enrolled SSH alias, not SSH options or a command')
    command = ('source /opt/ros/jazzy/setup.bash && '
               'source /opt/rosy/current/install/setup.bash && exec python3 -')
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=8', alias, 'sudo', '-n', 'bash', '-c', "'" + command + "'"]


def verdict(result):
    candidate = result.get('fit', {}).get('candidate', {})
    return 'CANDIDATE' if not result.get('faults') and candidate.get('recommended') is True else 'REJECTED'


def checked_output(path, root=None):
    path = path.resolve()
    if root is None and os.name == 'nt':
        root = Path('X:/DevTemp')
    if root is not None and not path.is_relative_to(root.resolve()):
        raise ValueError('Windows evidence belongs under X:/DevTemp')
    if path.exists():
        raise ValueError('Output exists; use a new run filename')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot', required=True, help='Previously enrolled pinned SSH alias')
    parser.add_argument('--output', type=Path, required=True, help='New local JSON evidence file')
    args = parser.parse_args(argv)
    try:
        args.output = checked_output(args.output)
    except ValueError as error:
        parser.error(str(error))
    command = ssh_command(args.robot)
    source = Path(__file__).with_name('camera_capture.py').read_bytes()
    run = subprocess.run(command, input=source, capture_output=True, timeout=180)
    if run.returncode:
        raise RuntimeError('Read-only camera capture failed; SSH exit ' + str(run.returncode))
    result = json.loads(run.stdout.decode('utf-8').splitlines()[-1])
    result['verdict'] = verdict(result)
    result['applied'] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'verdict': result['verdict'], 'applied': False,
                      'reason': result.get('fit', {}).get('error') or
                      result.get('fit', {}).get('candidate', {}).get('why'),
                      'output': str(args.output)}))
    return 0 if result['verdict'] == 'CANDIDATE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
