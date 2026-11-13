"""Read-only Fleet R / robot release and enrollment check.

    python tools/remote/fleet_robot_check.py [robot-id ...] --json-out C:/DevTemp/e2e-check/result.json

Robot names and SSH targets come from private/lab-hosts.json. No credential or digest
is returned from either remote probe. --active only requests the existing identify blink.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts  # noqa: E402
import update_ops  # noqa: E402


ROBOT_PROBE = r'''
import datetime, http.client, json, os, socket, ssl, subprocess, sys
from pathlib import Path

def run(*argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    return p.returncode, p.stdout.strip()

def env():
    out = {}
    for line in Path('/etc/rosy/runtime.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            out[key] = value.strip().strip('"\'')
    return out

result = {}
try:
    current = Path('/opt/rosy/current').resolve(strict=True)
    result['release'] = current.name
    p = subprocess.run(['sha256sum', '--quiet', '-c', 'SHA256SUMS'], cwd=current,
                       capture_output=True, timeout=120)
    result['checksum'] = p.returncode == 0
    result['signed'] = (current / 'SHA256SUMS.sig').is_file()
except Exception as exc:
    result['release_error'] = type(exc).__name__
for name, unit in [('core', 'rosy-core.service'), ('recover', 'rosy-release-recover.service')]:
    code, state = run('systemctl', 'is-active', unit)
    result[name] = state if code in (0, 3) else 'unknown'
try:
    import yaml
    config = yaml.safe_load(Path('/var/lib/rosy/core/.rosy/rosy.yaml').read_text()) or {}
    result['tokens'] = [{'id': row.get('id'), 'expires_at': row.get('expires_at')}
                        for row in config.get('auth', {}).get('tokens', [])]
except Exception as exc:
    result['token_error'] = type(exc).__name__
try:
    values = env()
    result['tls_configured'] = values.get('ROSY_API_TLS') == 'required'
    if result['tls_configured']:
        host = values['ROSY_API_TLS_HOST']
        port = int(values.get('ROSY_API_PORT', '8080'))
        context = ssl.create_default_context(cafile=values['ROSY_API_TLS_CA_FILE'])
        with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                secured.sendall(('GET /api/v1 HTTP/1.1\r\nHost: ' + host +
                                 '\r\nConnection: close\r\n\r\n').encode())
                response = http.client.HTTPResponse(secured)
                response.begin()
                result['tls'] = 200 <= response.status < 500
except Exception as exc:
    result['tls'] = False
    result['tls_error'] = type(exc).__name__
try:
    invocation = subprocess.run(['systemctl', 'show', 'rosy-core.service',
                                 '-p', 'InvocationID', '--value'], capture_output=True,
                                text=True, timeout=15, check=True).stdout.strip()
    if not invocation:
        raise ValueError('CORE invocation unavailable')
    journal = subprocess.run(['journalctl', '_SYSTEMD_INVOCATION_ID=' + invocation,
                              '-o', 'cat', '--no-pager', '-n', '2000'], capture_output=True,
                             text=True, timeout=15, check=True).stdout
    for line in journal.splitlines():
        if 'Fleet agent welcomed by hub' in line:
            result['hub_online'] = True
        elif any(message in line for message in ('Fleet agent disconnected:',
                 'Fleet agent link lost (', 'Fleet hub did not answer a heartbeat',
                 'Fleet agent link requires operator:', 'Fleet authentication rejected')):
            result['hub_online'] = False
except Exception:
    pass
print(json.dumps(result))
'''

FLEET_PROBE = r'''
import json, sqlite3
uri = 'file:/var/lib/rosy/fleet.sqlite3?mode=ro'
with sqlite3.connect(uri, uri=True, timeout=3) as db:
    rows = db.execute('SELECT robot_id, hostname, discovery_name, address, token_id, state, '
                      'expires_at, fleet_expires_at, hub_digest IS NOT NULL '
                      'FROM robot_enrollments').fetchall()
rows = [dict(robot_id=r[0], hostname=r[1], discovery_name=r[2], address=r[3],
                       token_id=r[4], state=r[5], expires_at=r[6],
                       fleet_expires_at=r[7], hub_linked=bool(r[8])) for r in rows]
print(json.dumps({'rows': rows}))
'''

IDENTIFY_PROBE = r'''
import http.client, json, socket, ssl, sys
from pathlib import Path
token = json.load(sys.stdin)
values = {}
for line in Path('/etc/rosy/runtime.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        values[key] = value.strip().strip('"\'')
if values.get('ROSY_API_TLS') != 'required':
    print(json.dumps({'ok': False, 'reason': 'TLS required'}))
    sys.exit()
try:
    host = values['ROSY_API_TLS_HOST']
    port = int(values['ROSY_API_PORT'])
    context = ssl.create_default_context(cafile=values['ROSY_API_TLS_CA_FILE'])
    with socket.create_connection(('127.0.0.1', port), timeout=4) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secured:
            body = b'{}'
            secured.sendall(('POST /api/v1/host/lamp/identify?quiet=true HTTP/1.1\r\n'
                             'Host: ' + host + '\r\nAuthorization: Bearer ' + token +
                             '\r\nContent-Type: application/json\r\nContent-Length: 2\r\n'
                             'Connection: close\r\n\r\n').encode() + body)
            response = http.client.HTTPResponse(secured)
            response.begin()
            result = json.loads(response.read(8192)) if response.status == 200 else {}
            print(json.dumps({'ok': response.status == 200 and result.get('accepted') is True,
                              'reason': 'accepted' if response.status == 200 else
                              'HTTP ' + str(response.status)}))
except Exception as exc:
    print(json.dumps({'ok': False, 'reason': type(exc).__name__}))
'''


def probe(argv: list[str], script: str, timeout: int = 150):
    try:
        done = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
        if done.returncode:
            return None, f'command exit {done.returncode}'
        return json.loads(done.stdout), None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return None, type(exc).__name__


def expiry(value) -> float | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def enrollment(rows: list[dict], robot_id: str, target: str) -> dict | None:
    """Resolve short lab IDs using the pinned enrollment identity, never row order."""
    names = {robot_id, f'rosy-pinky-{robot_id}', target.removesuffix('.local')}
    matches = [row for row in rows if row.get('robot_id') in names
               or row.get('hostname') in names or row.get('discovery_name') in names
               or row.get('address') == target]
    return matches[0] if len(matches) == 1 else None


def decide(robot_id: str, robot: dict | None, fleet: dict | None, *, robot_error=None,
           fleet_error=None, now: float | None = None) -> list[dict]:
    """Pure verdicts; no remote output, token value or digest enters a report."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    rows = []

    def add(check, ok, reason):
        rows.append(dict(robot=robot_id, check=check,
                         result='SKIP' if ok is None else 'PASS' if ok else 'FAIL', reason=reason))

    add('ssh', robot is not None, 'reachable' if robot is not None else robot_error or 'unreachable')
    if robot is None:
        for check in ('tls', 'release', 'checksum', 'core', 'recover', 'token'):
            add(check, False, 'robot probe unavailable')
    else:
        add('tls', robot.get('tls') is True, 'verified TLS' if robot.get('tls') else
            robot.get('tls_error', 'TLS unavailable'))
        add('release', bool(robot.get('release')), robot.get('release') or robot.get('release_error', 'missing'))
        add('checksum', robot.get('checksum') is True and robot.get('signed') is True,
            'signed metadata and checksums present' if robot.get('checksum') and robot.get('signed') else
            'signature file missing or checksum failed')
        add('core', robot.get('core') == 'active', robot.get('core', 'unknown'))
        add('recover', robot.get('recover') == 'active', robot.get('recover', 'unknown'))
    add('fleet', fleet is not None,
        'ledger row found' if fleet is not None else fleet_error or 'no matching enrollment')
    if fleet is not None:
        add('enrollment', fleet.get('state') == 'active', fleet.get('state', 'not enrolled'))
        add('hub_linked', fleet.get('hub_linked') is True,
            'linked' if fleet.get('hub_linked') else 'not linked')
    else:
        add('enrollment', False, 'no Fleet ledger row')
        add('hub_linked', False, 'no Fleet ledger row')
    if robot is not None and fleet is not None:
        match = next((t for t in robot.get('tokens', []) if t.get('id') == fleet.get('token_id')), None)
        actual, ledger = expiry(match.get('expires_at')) if match else None, expiry(fleet.get('expires_at'))
        if robot.get('token_error'):
            add('token', False, 'robot token metadata unreadable')
        elif match is None or actual is None or ledger is None:
            add('token', False, 'matching token or expiry missing')
        else:
            valid = actual > now and actual >= ledger
            robot_date = datetime.fromtimestamp(actual, timezone.utc).isoformat()
            fleet_date = datetime.fromtimestamp(ledger, timezone.utc).isoformat()
            add('token', valid, f'robot expiry {robot_date}; Fleet expiry {fleet_date}')
    elif robot is not None:
        add('token', False, 'Fleet or robot token metadata unavailable')
    if fleet is not None and robot is not None and 'hub_online' in robot:
        add('hub_online', robot['hub_online'] is True,
            'robot agent welcomed (journal)' if robot['hub_online'] else
            'robot agent disconnected (journal)')
    else:
        add('hub_online', None, 'robot agent journal state unavailable')
    add('lamp', None, 'no status-lamp read route in current CORE API')
    add('update', None, 'no update-status read route in current CORE API')
    return rows



def robot_ssh(target: str) -> list[str]:
    """The operator ssh alias (``rosy-pinky-<id>``): ~/.ssh/config proxies it through R's mDNS.

    ``update_ops.robot_ssh`` adds ``.local`` and the IP-pinned known_hosts; the alias's
    ProxyCommand appends ``.local`` itself, so that form resolves ``*.local.local`` and fails.
    """
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', target.removesuffix('.local')]

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('robots', nargs='*', help='robot ids from lab_hosts.json (default: all)')
    parser.add_argument('--json-out', type=Path, required=True)
    parser.add_argument('--active', action='store_true', help='request only a reversible identify blink')
    parser.add_argument('--admin-token-file', type=Path,
                        help='private JSON mapping lab robot IDs to CORE admin tokens; only with --active')
    args = parser.parse_args(argv)
    if args.admin_token_file and not args.active:
        parser.error('--admin-token-file requires --active')
    tokens = json.loads(args.admin_token_file.read_text(encoding='utf-8')) if args.admin_token_file else {}
    if not isinstance(tokens, dict):
        parser.error('--admin-token-file must contain a JSON object')
    known = lab_hosts.robots()
    targets = args.robots or sorted(known)
    if not targets or any(item not in known for item in targets):
        parser.error('select robot ids present in private/lab-hosts.json')
    site = lab_hosts.ssh_target(lab_hosts.site_host(), 'site_host')
    fleet_rows, fleet_error = probe([*update_ops.host_ssh(site), 'sudo', '-n', 'docker',
                                    'exec', '-i', '-u', 'rosy', 'rosy-site-fleet-1',
                                    'python3', '-'], FLEET_PROBE, 30)
    fleet_rows = fleet_rows.get('rows', []) if isinstance(fleet_rows, dict) else []
    results = []
    for robot_id in targets:
        target = lab_hosts.ssh_target(known[robot_id], 'robots')
        robot, error = probe([*robot_ssh(target), 'sudo', '-n', 'python3', '-'], ROBOT_PROBE)
        row = enrollment(fleet_rows, robot_id, target)
        results.extend(decide(robot_id, robot, row, robot_error=error,
                              fleet_error=fleet_error))
        if args.active:
            token = tokens.get(robot_id)
            if robot is None or robot.get('tls') is not True or not isinstance(token, str) or not token:
                state, reason = 'SKIP', 'verified TLS and private admin token required'
            else:
                active, error = probe([*robot_ssh(target), 'sudo', '-n', 'python3',
                                       '-c', shlex.quote(IDENTIFY_PROBE)], json.dumps(token), 15)
                state = 'PASS' if isinstance(active, dict) and active.get('ok') else 'FAIL'
                reason = active.get('reason', 'unknown') if isinstance(active, dict) else error or 'unavailable'
            results.append(dict(robot=robot_id, check='identify', result=state, reason=reason))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print('ROBOT CHECK RESULT REASON')
    for row in results:
        print(f"{row['robot']} {row['check']} {row['result']} {row['reason']}")
    return int(any(row['result'] == 'FAIL' for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
