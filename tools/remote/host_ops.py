"""PC service control from the operator PC when Fleet is down (D-991).

    python tools/remote/host_ops.py list
    python tools/remote/host_ops.py <site|ai|model> reboot --confirm <host>
    python tools/remote/host_ops.py <site|ai|model> reboot-over-jobs --confirm <host>
    python tools/remote/host_ops.py <site|ai|model> cancel-reboot --confirm <host>
    python tools/remote/host_ops.py <site|ai|model> clean-storage --confirm <host>
    python tools/remote/host_ops.py <site|ai|model> restart-unit <unit> --confirm <host>

It takes the same closed list as the Fleet screen and asks the same helper on that PC, so the helper's
refusals (a running arm session, live jobs) hold here too. The record is the PC's journal
(`journalctl -t rosy-host-control`); Fleet's history does not see these, since Fleet may be the thing
that is down. Use the Fleet screen whenever it answers.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts  # noqa: E402

HELPER = '/usr/local/sbin/rosy-host-control'
MEANING = {
    2: 'the helper refused: not allowed on this PC, or its installed helper is older than this list',
    3: 'a reboot is already scheduled',
    4: 'no reboot scheduled by this helper to cancel',
    5: 'this PC has no storage service',
    6: 'an arm session is running; nothing passes it',
    7: 'a job is running; reboot-over-jobs cuts it',
}


def _control():
    # By path: the fleet package needs Fleet's dependencies and this module needs none of them.
    path = Path(__file__).resolve().parents[2] / 'operations/fleet/fleet/host_control.py'
    spec = importlib.util.spec_from_file_location('rosy_host_control', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def targets(config: dict) -> dict[str, str]:
    found = {'site': config['site_host']} if config.get('site_host') else {}
    found.update({role: target for target, role in lab_hosts.sim_roles(config).items() if role})
    return found


def run(host: str, action: str, unit: str | None, config: dict, *, runner=subprocess.run) -> int:
    control = _control()
    try:
        command = control.decide(host, action, unit, confirmed=True)
    except control.HostControlError as error:
        print(f'{host} {action}: {error.code}', file=sys.stderr)
        return 2
    target = targets(config).get(host)
    if target is None:
        print(f'{host}: no SSH target in lab-hosts.json', file=sys.stderr)
        return 2
    done = runner(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', target,
                   'sudo', '-n', HELPER, *command['argv']], check=False, timeout=60)
    if done.returncode:
        print(f'{host} {action}: {MEANING.get(done.returncode, f"failed with exit {done.returncode}")}', file=sys.stderr)
    return done.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('host')
    parser.add_argument('action', nargs='?')
    parser.add_argument('unit', nargs='?')
    parser.add_argument('--confirm', help='the host name again: these actions are hard to take back')
    args = parser.parse_args(argv)
    if args.host == 'list':
        for row in _control().catalogue()['hosts']:
            print(row['host'], ' '.join(row['actions']), *row['units'])
        return 0
    if not args.action or args.confirm != args.host:
        parser.error('give an action and --confirm <host>')
    return run(args.host, args.action, args.unit, lab_hosts.load())


if __name__ == '__main__':
    raise SystemExit(main())
