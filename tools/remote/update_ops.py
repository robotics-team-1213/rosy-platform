"""One operator CLI for every update channel (D-957): status / run-now / hold / resume.

    python tools/remote/update_ops.py targets
    python tools/remote/update_ops.py status   all|robots|site|<robot name>|<ssh target> [--unit rosy-*.service]
    python tools/remote/update_ops.py run-now  <selector>
    python tools/remote/update_ops.py hold     <selector> --reason R [--hours H] [--holder id]
    python tools/remote/update_ops.py resume   <selector>
    python tools/remote/update_ops.py forget-failed site <tag>

run-now only skips the timer wait: every surface's own gates (idle, battery,
signature, freeze) keep their authority. Robot holds are the device CLI's
time-boxed hold (D-412), the site stack keeps its state-file hold (D-441), and
PC user units stop by disabling their timer, recorded in the operator-PC ledger
private/update-holds.json. Nothing here is installed on any host.
"""
from __future__ import annotations
import argparse
import datetime as _dt
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts

# load by file location, not sys.path: tools/release must not shadow a repo package here
_spec = importlib.util.spec_from_file_location(
    'update_status', Path(__file__).resolve().with_name('update_status.py'))
update_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_status)
PROBE = update_status.PROBE

HOST_SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
ROBOT_UNIT = 'rosy-auto-update.service'
ROBOT_CLI = '/opt/rosy/native-runtime/rosy_auto_update.py'
SITE_CLI = '/usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py'
SITE_UNIT = 'rosy-site-autoupdate.service'
REASON_OK = re.compile(r'[A-Za-z0-9][A-Za-z0-9 .,:_/()+=@-]{0,199}\Z')
HOLDER_OK = re.compile(r'[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\Z')
UNIT_OK = re.compile(r'rosy-[a-z0-9@._-]+\.service\Z')
TAG_OK = re.compile(r'site-[0-9a-f]{6,12}\Z')


def robot_ssh(host: str) -> list[str]:
    """The rosy-update-hold.ps1 path: operator key and pinned known_hosts under LOCALAPPDATA."""
    base = Path(os.environ.get('LOCALAPPDATA', ''))
    known = f'{base}/Rosy/known_hosts'
    target = host if '@' in host else f'rosy@{host}'
    return ['ssh', '-i', str(base / 'Rosy/ssh/rosy-operator-ed25519'),
            '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}',
            '-o', 'ConnectTimeout=5', target]


def host_ssh(target: str) -> list[str]:
    return ['ssh', *HOST_SSH[1:], target]


# selection

def updater_units(inventory: dict, host_roles: dict) -> dict:
    """Per host, the services.yaml `channel: updater` oneshot services (no timers, no retired)."""
    units = {}
    for host, roles in host_roles.items():
        names = {name for role in sorted(roles) for name, entry in inventory.get(role, {}).items()
                 if entry.get('channel') == 'updater' and entry.get('run') == 'oneshot'
                 and name.endswith('.service')}
        units[host] = sorted(names)
    return units


def resolve(config: dict, inventory: dict, selector: str, robots: dict | None = None) -> list[dict]:
    """Selector -> targets; one target per host, channels are (kind, unit-or-None)."""
    robots = lab_hosts.robots() if robots is None else robots
    units = updater_units(inventory, update_status.roles(config))
    raw_site = str(config.get('site_host') or '').strip()
    site = lab_hosts.ssh_target(raw_site, 'site_host') if raw_site else ''

    def host_target(host: str) -> dict:
        channels = ([('site-stack', None)] if host == site else []) + [
            ('user-unit', name) for name in units.get(host, [])]
        return {'host': host, 'channels': channels}

    if selector == 'robots':
        return [{'host': host, 'channels': [('robot', None)]} for host in robots.values()]
    if selector == 'site':
        if not site:
            raise SystemExit('no site_host in private/lab-hosts.json')
        return [host_target(site)]
    if selector in robots:
        return [{'host': robots[selector], 'channels': [('robot', None)]}]
    if selector in units:
        return [host_target(selector)]
    if selector == 'all':
        targets = [{'host': host, 'channels': [('robot', None)]} for host in robots.values()]
        for host in sorted(set(units) | ({site} if site else set())):
            target = host_target(host)
            if target['channels']:
                targets.append(target)
        return targets
    raise SystemExit(f'unknown selector: {selector} (all, robots, site, a robot name, or an SSH target)')


def apply_unit_filter(targets: list[dict], unit_name: str) -> list[dict]:
    if not unit_name or not UNIT_OK.fullmatch(unit_name):
        raise SystemExit(f'not a rosy service unit: {unit_name}')
    kept = [{'host': t['host'], 'channels': [c for c in t['channels'] if c == ('user-unit', unit_name)]}
            for t in targets]
    kept = [t for t in kept if t['channels']]
    if not kept:
        raise SystemExit(f'no channel matches unit {unit_name} in the selection')
    return kept


# commands

def commands(target: dict, action: str, *, reason: str | None = None, hours=None,
             holder: str | None = None, tag: str | None = None) -> list[tuple]:
    """(channel, argv) pairs for one target; status runs only the robot/site native CLIs."""
    out = []
    for channel in target['channels']:
        kind, name = channel
        if kind == 'robot':
            if action == 'hold':
                remote = (f'sudo -n python3 {ROBOT_CLI} hold --holder \'{holder}\' '
                          f'--reason \'{reason}\' --hours {hours:g}')
            elif action == 'resume':
                remote = f'sudo -n python3 {ROBOT_CLI} release-hold'
            elif action == 'status':
                remote = f'sudo -n python3 {ROBOT_CLI} status --json'
            else:
                remote = f'sudo -n systemctl start {ROBOT_UNIT}'
            out.append((channel, [*robot_ssh(target['host']), remote]))
        elif kind == 'site-stack':
            if action == 'hold':
                remote = f'sudo -n {SITE_CLI} hold {shlex.quote(reason)}'
            elif action == 'resume':
                remote = f'sudo -n {SITE_CLI} resume'
            elif action == 'status':
                remote = f'sudo -n {SITE_CLI} status'
            elif action == 'forget-failed':
                remote = f'sudo -n {SITE_CLI} forget-failed {tag}'
            else:
                remote = f'sudo -n systemctl start {SITE_UNIT}'
            out.append((channel, [*host_ssh(target['host']), remote]))
        elif action in ('run-now', 'hold', 'resume'):
            stem = name.rsplit('.service', 1)[0]
            remote = {'run-now': f'systemctl --user start {name}',
                      'hold': f'systemctl --user disable --now {stem}.timer',
                      'resume': f'systemctl --user enable --now {stem}.timer'}[action]
            out.append((channel, [*host_ssh(target['host']), remote]))
    return out


# hold ledger (PC user units have no host-side hold state; robots and the site do)

def unit_key(kind: str, name: str | None) -> str:
    return name if kind == 'user-unit' else kind


def ledger_path() -> Path:
    marker = lab_hosts.host_file()
    root = marker.parent if marker else Path(__file__).resolve().parents[2] / 'private'
    return root / 'update-holds.json'


def load_ledger(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_ledger(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def add_hold(path, host: str, unit: str, reason: str, holder: str) -> None:
    data = load_ledger(path)
    data[f'{host}|{unit}'] = {'reason': reason, 'holder': holder,
                              'at': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')}
    save_ledger(path, data)


def remove_hold(path, host: str, unit: str) -> None:
    data = load_ledger(path)
    data.pop(f'{host}|{unit}', None)
    save_ledger(path, data)


def _default_holder() -> str:
    user = os.environ.get('USERNAME') or 'agent'
    machine = os.environ.get('COMPUTERNAME') or socket.gethostname() or 'pc'
    return f'{user}@{machine}'


# execution

def execute(targets: list[dict], action: str, run, *, reason: str | None = None, hours=None,
            holder: str | None = None, tag: str | None = None, ledger=None) -> int:
    if action == 'hold':
        if not reason:
            raise ValueError('hold needs --reason <text>')
        holder = holder or _default_holder()
        if not HOLDER_OK.fullmatch(holder):
            raise ValueError(f'holder must be 1-64 characters of letters, digits and . _ @ -: {holder}')
        kinds = {kind for target in targets for kind, _ in target['channels']}
        if hours is not None:
            if not 0 < hours <= 168:
                raise ValueError('hours must be greater than 0 and at most 168')
            if kinds - {'robot'}:
                raise ValueError('--hours is for robot-only selections; site and unit holds have no expiry')
        elif 'robot' in kinds:
            raise ValueError('a robot hold always expires: pass --hours (max 168)')
        if 'robot' in kinds and not REASON_OK.fullmatch(reason):
            raise ValueError('reason must be 1-200 characters of letters, digits, space and '
                             '. , : _ / ( ) + = @ - starting with a letter or digit')
    if action == 'forget-failed':
        if not tag or not TAG_OK.fullmatch(tag):
            raise ValueError('forget-failed needs a site tag like site-<sha12>')
        if {kind for target in targets for kind, _ in target['channels']} - {'site-stack'}:
            raise ValueError('forget-failed is site-only')
    failures = 0
    for target in targets:
        if action == 'run-now' and ledger is not None:
            for key, entry in load_ledger(ledger).items():
                if key.startswith(f"{target['host']}|"):
                    print(f'  note: held ({entry["reason"]}) by {entry["holder"]} — running once anyway')
        if action == 'resume' and ledger is not None:
            held = load_ledger(ledger)
            for channel in target['channels']:
                key = f"{target['host']}|{unit_key(*channel)}"
                if channel[0] == 'user-unit' and key not in held:
                    print(f'  note: no ledger entry for {key} (held outside this tool?)')
        for channel, argv in commands(target, action, reason=reason, hours=hours, holder=holder, tag=tag):
            print(' '.join(argv))
            code, output = run(argv)
            if output:
                print('  ' + output.strip().replace('\n', '\n  '))
            if code != 0:
                print(f'  FAILED exit {code}: {target["host"]} {unit_key(*channel)}')
                failures += 1
                continue
            if ledger is None:
                continue
            if action == 'hold' and channel[0] == 'user-unit':
                add_hold(ledger, target['host'], channel[1], reason, holder)
            if action == 'resume' and channel[0] == 'user-unit':
                remove_hold(ledger, target['host'], channel[1])
    return 1 if failures else 0


# status

def status_lines(target: dict, run, ledger=None, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    lines = [f"{target['host']}:"]
    for _, argv in commands(target, 'status'):
        code, output = run(argv)
        lines.append('  ' + (output.strip() if output else f'no output (exit {code})').replace('\n', '\n  '))
    units = [name for kind, name in target['channels'] if kind == 'user-unit']
    if units:
        code, output = run([*host_ssh(target['host']), 'bash -s'], input=PROBE.encode())
        if code != 0:
            lines.append(f'  probe failed (exit {code})')
        else:
            host = update_status.parse(output, now, 6.0)
            lines.append(f"  gate {host['gate']}")
            for found in host['channels']:
                if found['unit'] not in units:
                    continue
                lines.append(f"  {found['verdict']:5} {found['unit']}: {found['step']} {found['release']} "
                             f"timer={found['timer']} healthy={found['healthy_h']}h ago"
                             + (f" reason={found['reason']}" if found['reason'] else ''))
    if ledger is not None:
        for key, entry in load_ledger(ledger).items():
            if key.startswith(f"{target['host']}|"):
                lines.append(f"  held ({entry['reason']}) by {entry['holder']} since {entry['at']}")
    return lines


def _ssh_run(argv, input=None):
    done = subprocess.run(argv, input=input, capture_output=True, timeout=180)
    return done.returncode, done.stdout.decode(errors='replace')


def main(argv=None, *, config=None, inventory=None, robots=None, run=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['targets', 'status', 'run-now', 'hold', 'resume', 'forget-failed'])
    parser.add_argument('selector', help='all | robots | site | <robot name> | <ssh target>')
    parser.add_argument('--unit', help='narrow a host selection to one updater service')
    parser.add_argument('--reason')
    parser.add_argument('--hours', type=float)
    parser.add_argument('--holder')
    parser.add_argument('--tag', help='site-<sha12> for forget-failed')
    args = parser.parse_args(argv)
    try:
        config = lab_hosts.load() if config is None else config
        inventory = update_status.load_inventory() if inventory is None else inventory
        targets = resolve(config, inventory, args.selector, robots=robots)
        if args.unit:
            targets = apply_unit_filter(targets, args.unit)
    except SystemExit as error:
        print(error)
        return 2
    if args.action == 'targets':
        for target in targets:
            print(target['host'])
            for kind, name in target['channels']:
                print(f'  {kind} {name or ""}'.rstrip())
        return 0
    ledger = ledger_path()
    if args.action == 'status':
        for target in targets:
            for line in status_lines(target, run=run or _ssh_run, ledger=ledger):
                print(line)
        return 0
    try:
        return execute(targets, args.action, run=run or _ssh_run, reason=args.reason,
                       hours=args.hours, holder=args.holder, tag=args.tag, ledger=ledger)
    except ValueError as error:
        print(error)
        return 2


if __name__ == '__main__':
    sys.exit(main())
