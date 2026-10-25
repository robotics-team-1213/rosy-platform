"""Show every lab PC's update channel at a glance; read-only (D-805).

    python tools/remote/update_status.py

For each host in private/lab-hosts.json, this reads the freeze gate, every rosy user
update unit (`*autoupdate*`, `*-update`), its last JSON step and result, and the rosy units
systemd lists as failed. A channel is `STUCK` when its unit failed or it logged no healthy step
(switched, up_to_date, idle, active) within `--stale-hours` (default 6); a disabled timer is `OFF`.
Exit 1 when any channel is STUCK or a host is unreachable. Nothing is started, stopped or changed.

It also lists where each running rosy service's code comes from (its ExecStart and environment
files): an auto-updated `current` link, a pinned `release` commit, or `ADHOC` (a `~/rosy-test`
copy, which no updater or installer owns). Pinned and ad hoc sources do not change the exit code.

D-852: each host is then checked against `deploy/hosts/services.yaml` for its role (the site host
is `site`, `sim_hosts` entries give `model`/`ai`). An installed rosy/pinky unit file with no entry is
UNDECLARED; a declared unit that is absent is MISSING; a unit that should run but does not is DOWN;
an `off` unit that is enabled or running is UNEXPECTED; a unit file, copied file, code path or
drop-in that differs from its declaration is DRIFT. Any of these exits 1. `adhoc` entries are listed,
and a DRIFT the entry explains in `known_drift` is reported as KNOWN with its reason.
"""
from __future__ import annotations

import argparse
from fnmatch import fnmatch
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts

SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
PROBE = r'''
gate=$( [ -x /usr/local/bin/rosy-update-gate ] && { /usr/local/bin/rosy-update-gate >/dev/null 2>&1 && echo open || echo frozen; } || echo missing )
echo "gate $gate"
for u in $(systemctl --user list-unit-files --no-legend 'rosy-*' 2>/dev/null | awk '{print $1}' | grep -E '(autoupdate|-update)\.service$'); do
  result=$(systemctl --user show "$u" -p Result --value)
  timer=$(systemctl --user is-enabled "${u%.service}.timer" 2>/dev/null || echo none)
  log=$(journalctl --user -u "$u" --no-pager -n 400 -o short-unix 2>/dev/null | grep -v -E ' systemd\[|rosy-update-gate:')
  # JSON updaters log a step; the review release updater (auto_review_release.py) logs plain text
  healthy=$(printf '%s\n' "$log" | grep -E '"(step|result)": "(switched|up_to_date|idle|active)"|]: (already active|activated): |]: waiting for a newer accepted' | tail -1 | cut -d' ' -f1)
  last=$(printf '%s\n' "$log" | grep '{' | tail -1)
  [ -z "$last" ] && last=$(printf '%s\n' "$log" | tail -1)
  echo "unit $u $result $timer ${healthy:--} $last"
done
for f in $(systemctl --user --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | grep '^rosy-'); do echo "failed $f"; done
for u in $(systemctl --user list-units --no-legend --plain --type=service --state=active 'rosy-*' 'pinky-*' 2>/dev/null | awk '{print $1}'); do
  envs=$(systemctl --user show "$u" -p EnvironmentFiles --value | grep -oE '/[^ ]+' | grep -v '^/dev')
  # with bash -s, stdin is the rest of this script: never let a command read it
  exec=$(systemctl --user show "$u" -p ExecStart --value)
  pattern='/home/[^ "=:;]*(/rosy-test/[^/ "]+|/releases/[^/ "]+|/source/[0-9a-f]{40}|/current)'
  src=
  # the program's own *_SOURCE / *_ROOT variable names its code; other env paths (a Python, a camera source) do not
  for v in $(printf '%s' "$exec" | grep -oE 'ROSY_[A-Z_]*(SOURCE|ROOT)' | awk '!seen[$0]++'); do
    src=$(cat $envs </dev/null 2>/dev/null | grep "^$v=" | tail -1 | grep -oE "$pattern" | head -1)
    [ -n "$src" ] && break
  done
  [ -z "$src" ] && src=$(printf '%s %s' "$exec" "$(cat $envs </dev/null 2>/dev/null)" | grep -oE "$pattern" | head -1)
  [ -z "$src" ] && src=$(printf '%s %s' "$exec" "$(cat $envs </dev/null 2>/dev/null)" | grep -oE '/home/[^ "=:;]+\.(py|sh)' | head -1)
  echo "svc $u ${src:--}"
done
cd ~/.config/systemd/user 2>/dev/null && for n in rosy-*.service rosy-*.timer pinky-*.service pinky-*.timer; do
  [ -f "$n" ] || continue
  en=$(systemctl --user is-enabled "$n" 2>/dev/null)
  case "$n" in *@.*) ac=template;; *) ac=$(systemctl --user is-active "$n" 2>/dev/null);; esac
  echo "file $n ${en:-unknown} ${ac:-unknown} $(tr -d '\r' < "$n" | sha256sum | cut -c1-64) $(ls "$n.d" 2>/dev/null | tr '\n' ',')"
done
for i in $(systemctl --user list-units --no-legend --plain --all 'rosy-*@*' 'pinky-*@*' 2>/dev/null | awk '{print $1}'); do
  echo "inst $i $(systemctl --user is-active "$i") $(ls ~/.config/systemd/user/"$i".d 2>/dev/null | tr '\n' ',')"
done
for c in "$@"; do
  if [ -f "$HOME/$c" ]; then echo "copy $c $(tr -d '\r' < "$HOME/$c" | sha256sum | cut -c1-64)"; else echo "copy $c missing"; fi
done
true
'''
HEALTHY = {'switched', 'up_to_date', 'idle', 'active'}


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None


def classify(source: str) -> dict:
    """Name a service's code source: ADHOC rosy-test copy, auto-updated current link, or pinned release."""
    name = source.rstrip('/').rsplit('/', 1)[-1]
    if '/rosy-test/' in source:
        return dict(kind='ADHOC', where=name)
    if source.endswith('/current'):
        return dict(kind='current', where=source.rsplit('/', 2)[-2])
    if '/releases/' in source or '/source/' in source:
        return dict(kind='release', where=name[:12])
    return dict(kind='other', where='-')


def parse(text: str, now: float, stale_hours: float) -> dict:
    """One host's probe output -> channels; a channel is STUCK when it has not been healthy recently.

    A short deferral (a running job, waiting for CI) is normal; the same deferral for longer than
    `stale_hours` is what hid the field PC (4 days) and AI PC (3 days) stalls in October.
    """
    host = dict(gate='unknown', channels=[], failed=[], sources=[], files={}, instances={}, copies={}, paths={})
    for raw in text.splitlines():
        kind, _, rest = raw.partition(' ')
        if kind == 'gate':
            host['gate'] = rest.strip()
        elif kind == 'failed':
            host['failed'].append(rest.strip())
        elif kind == 'svc':
            unit, _, source = rest.strip().partition(' ')
            host['sources'].append(dict(unit=unit, **classify(source)))
            host['paths'][unit] = source
        elif kind == 'file':
            name, enabled, active, digest, dropins = (rest.split(' ') + ['', '', '', '', ''])[:5]
            host['files'][name] = dict(enabled=enabled, active=active, sha256=digest,
                                       dropins=[d for d in dropins.split(',') if d])
        elif kind == 'inst':
            name, active, dropins = (rest.split(' ') + ['', '', ''])[:3]
            host['instances'][name] = dict(active=active, dropins=[d for d in dropins.split(',') if d])
        elif kind == 'copy':
            path, _, digest = rest.strip().partition(' ')
            host['copies'][path] = digest
        elif kind == 'unit':
            fields = rest.split(' ', 5)
            unit, result, timer, healthy = (fields + ['', '', '', ''])[:4]
            last = fields[5] if len(fields) > 5 else ''
            step = {}
            if '{' not in last and ']: ' in last:  # plain-text updater: "already active: <release>"
                step = {'step': last.split(']: ', 1)[1].split(':', 1)[0].strip()[:40]}
            if '{' in last:
                try:
                    step = json.loads(last[last.index('{'):])
                except ValueError:
                    step = {}
            healthy_at = _number(healthy)
            age = None if healthy_at is None else round((now - healthy_at) / 3600, 1)
            if timer == 'disabled':
                verdict = 'OFF'
            elif result != 'success' or age is None or age > stale_hours:
                verdict = 'STUCK'
            else:
                verdict = 'ok'
            host['channels'].append(dict(unit=unit, result=result, timer=timer, verdict=verdict,
                                         step=step.get('step') or step.get('result') or 'none',
                                         reason=step.get('reason'), healthy_h=age,
                                         release=step.get('release') or str(step.get('desired_commit', ''))[:12]))
    return host


FAILING = {'UNDECLARED', 'MISSING', 'DOWN', 'UNEXPECTED', 'DRIFT'}


def load_inventory(path: Path | None = None) -> dict:
    import yaml
    path = path or Path(__file__).resolve().parents[2] / 'deploy/hosts/services.yaml'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'rosy.host-services/1':
        raise SystemExit(f'{path}: unsupported schema')
    for units in data['roles'].values():
        for name, entry in units.items():
            if not isinstance(entry.get('run'), str):  # YAML 1.1 reads a bare off as false
                raise SystemExit(f'{path}: {name} run must be a quoted string')
    return data['roles']


def roles(config: dict) -> dict:
    """Host -> role: the site host is `site`; `sim_hosts` entries are `<ssh>=<role>`."""
    found = {}
    for entry in config.get('sim_hosts') or []:
        target, _, role = str(entry).partition('=')
        if role:
            found[target.strip()] = role.strip()
    if config.get('site_host'):
        found[str(config['site_host']).strip()] = 'site'
    return found


def repo_digest(spec: str, platform: Path, ops: Path) -> str | None:
    """sha256 (CR removed) of origin/main's copy of a repo file; `rosy-ops:<path>` reads the ops checkout."""
    root, path = (ops, spec.split(':', 1)[1]) if spec.startswith('rosy-ops:') else (platform, spec)
    for ref in ('origin/main', 'HEAD'):
        done = subprocess.run(['git', '-C', str(root), 'show', f'{ref}:{path}'], capture_output=True)
        if done.returncode == 0:
            return hashlib.sha256(done.stdout.replace(b'\r', b'')).hexdigest()
    return None


def _code_path_matches(path: str, pattern: str) -> bool:
    relative = path.split('/', 3)[3] if path.startswith('/home/') and path.count('/') >= 3 else path
    return fnmatch(relative, pattern) or fnmatch(relative, pattern.rstrip('/') + '/*')


def audit(declared: dict, host: dict, digest) -> list:
    """Compare one host's probe with its role's declaration; return (verdict, unit, detail) findings."""
    findings = []
    for name in sorted(set(host['files']) - set(declared)):
        findings.append(('UNDECLARED', name, 'installed but not in deploy/hosts/services.yaml'))
    for name, entry in declared.items():
        installed = host['files'].get(name)
        run = entry['run']
        if installed is None:
            if run != 'off':
                findings.append(('MISSING', name, 'declared but no unit file is installed'))
            continue
        units = [name.replace('@.', f'@{i}.') for i in entry.get('instances', [])] if '@.' in name else [name]
        if run == 'off':
            if installed['enabled'] == 'enabled' or installed['active'] == 'active':
                findings.append(('UNEXPECTED', name, f'declared off but {installed["enabled"]}/{installed["active"]}'))
        elif '@.' in name:
            for unit in units:
                if host['instances'].get(unit, {}).get('active') != 'active':
                    findings.append(('DOWN', unit, 'declared instance is not active'))
        elif run == 'active' and installed['active'] != 'active':
            findings.append(('DOWN', name, f'declared active but {installed["active"]}'))
        elif run == 'timer' and (installed['enabled'] != 'enabled' or installed['active'] != 'active'):
            findings.append(('DOWN', name, f'declared timer but {installed["enabled"]}/{installed["active"]}'))
        if entry.get('template'):
            expected = digest(entry['template'])
            if expected is None:
                findings.append(('note', name, f'cannot read template {entry["template"]}'))
            elif expected != installed['sha256']:
                findings.append(('DRIFT', name, f'unit file differs from {entry["template"]}'))
        for installed_path, repo_path in (entry.get('copies') or {}).items():
            expected, actual = digest(repo_path), host['copies'].get(installed_path)
            if actual in (None, 'missing'):
                findings.append(('DRIFT', name, f'~/{installed_path} is missing'))
            elif expected is None:
                findings.append(('note', name, f'cannot read {repo_path}'))
            elif expected != actual:
                findings.append(('DRIFT', name, f'~/{installed_path} differs from {repo_path}'))
        allowed = set(entry.get('dropins') or [])
        for unit in dict.fromkeys([name, *units]):
            record = installed if unit == name else host['instances'].get(unit)
            for dropin in (record or {}).get('dropins', []):
                if dropin not in allowed:
                    findings.append(('DRIFT', unit, f'undeclared drop-in {dropin}'))
        for unit in units:
            path = host['paths'].get(unit)
            if entry.get('source') and path and path != '-' and not _code_path_matches(path, entry['source']):
                findings.append(('DRIFT', unit, f'code from {path}, declared {entry["source"]}'))
        if entry['channel'] == 'adhoc':
            findings.append(('ADHOC', name, entry.get('note', 'declared adhoc')))
    reasons = {unit: entry['known_drift'] for name, entry in declared.items() if entry.get('known_drift')
               for unit in [name, *(name.replace('@.', f'@{i}.') for i in entry.get('instances', []))]}
    return [('KNOWN', unit, f'{detail} ({reasons[unit]})') if verdict == 'DRIFT' and unit in reasons
            else (verdict, unit, detail) for verdict, unit, detail in findings]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stale-hours', type=float, default=6.0)
    args = parser.parse_args()
    head = subprocess.run(['git', 'rev-parse', '--short=12', 'origin/main'], capture_output=True, text=True).stdout.strip()
    print(f'origin/main {head or "unknown (git fetch first)"}')
    stuck = False
    inventory = load_inventory()
    role_of = roles(lab_hosts.load())
    platform = Path(__file__).resolve().parents[2]
    ops = lab_hosts.main_checkout().parent / 'rosy-ops'
    digests = {}

    def digest(spec):
        if spec not in digests:
            digests[spec] = repo_digest(spec, platform, ops)
        return digests[spec]
    for target in dict.fromkeys(lab_hosts.test_hosts() + [lab_hosts.site_host()]):
        if not target:
            continue
        declared = inventory.get(role_of.get(target), {})
        copies = sorted({path for entry in declared.values() for path in (entry.get('copies') or {})})
        # bytes, not text: Windows text mode would send CRLF into bash
        done = subprocess.run([*SSH, '--', target, 'bash -s -- ' + ' '.join(copies)], input=PROBE.encode(),
                              capture_output=True, timeout=120)
        if done.returncode:
            print(f'\n{target}: UNREACHABLE ({done.stderr.decode(errors="replace").strip()[-120:]})')
            stuck = True
            continue
        host = parse(done.stdout.decode(errors='replace'), time.time(), args.stale_hours)
        print(f'\n{target}: gate {host["gate"]}')
        for c in host['channels']:
            print(f'  {c["verdict"]:5} {c["unit"]}: {c["step"]} {c["release"]} result={c["result"]} '
                  f'timer={c["timer"]} healthy={c["healthy_h"]}h ago' + (f' reason={c["reason"]}' if c['reason'] else ''))
            stuck |= c['verdict'] == 'STUCK'
        if not host['channels']:
            print('  (no rosy update unit)')
        for unit in host['failed']:
            print(f'  failed unit: {unit}')
        for src in host['sources']:
            if src['kind'] != 'other':
                print(f'  {src["kind"]:7} {src["unit"]}: {src["where"]}')
        if target not in role_of:
            print('  (no role in private/lab-hosts.json; services.yaml not checked)')
            continue
        findings = audit(declared, host, digest)
        for verdict, unit, detail in findings:
            print(f'  {verdict:10} {unit}: {detail}')
        print(f'  {role_of[target]}: {len(declared)} declared units, {sum(f[0] in FAILING for f in findings)} findings')
        stuck |= any(f[0] in FAILING for f in findings)
    sys.exit(1 if stuck else 0)


if __name__ == '__main__':
    main()
