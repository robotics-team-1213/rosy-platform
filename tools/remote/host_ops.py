"""PC service control and status queries via Fleet HTTPS API (preferred) or SSH (D-991).

    python tools/remote/host_ops.py list
    python tools/remote/host_ops.py status [--json]
    python tools/remote/host_ops.py <site|ai|model|cell> <action> [unit] --confirm <host> [--via-api | --via-ssh]

Uses the same closed list as the Fleet Maintenance screen (`/api/fleet/hosts`, `/control`) and the
same `/usr/local/sbin/rosy-host-control` helper on each PC, so arm-session and live-job refusals
hold identically across UI, API, and SSH. Defaults to HTTPS API when operator credentials exist.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_hosts  # noqa: E402

HELPER = '/usr/local/sbin/rosy-host-control'
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ERROR_BYTES = 65_536
_LOOPBACK = frozenset({'127.0.0.1', 'localhost', '::1'})
MEANING = {
    2: 'the helper refused: not allowed on this PC, or its installed helper is older than this list',
    3: 'a reboot is already scheduled',
    4: 'no reboot scheduled by this helper to cancel',
    5: 'this PC has no storage or maintenance service',
    6: 'an arm session is running; nothing passes it',
    7: 'a job is running; reboot-over-jobs cuts it',
}
_CODE_TO_EXIT = {
    'ACCEPTED': 0,
    'REBOOT_ALREADY_SCHEDULED': 3,
    'NO_HOST_CONTROL_REBOOT': 4,
    'NO_STORAGE_SERVICE': 5,
    'ARM_SESSION_ACTIVE': 6,
    'HOST_JOBS_ACTIVE': 7,
}
_VALIDATION_CODES = frozenset({
    'CONFIRMATION_REQUIRED', 'UNKNOWN_HOST', 'UNKNOWN_ACTION', 'UNIT_NOT_ALLOWED', 'ACTION_NOT_ALLOWED',
})


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
    if config.get('omx_hosts'):
        found['cell'] = lab_hosts.omx_hosts(config)[0]
    return found


def _validate_url(raw: str, label: str, *, allow_query: bool = False) -> tuple[str, str]:
    text = raw.strip()
    if not text or any(ord(c) < 0x20 or ord(c) == 0x7f for c in text):
        raise ValueError(f'invalid {label}')
    parsed = urllib.parse.urlsplit(text)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or '').lower()
    try:
        port = parsed.port
    except ValueError:
        raise ValueError(f'invalid {label}') from None
    if (not host or '\\' in parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.fragment or (not allow_query and parsed.query)):
        raise ValueError(f'invalid {label}')
    host_part = f'[{host}]' if ':' in host else host
    if scheme != 'https' and not (scheme == 'http' and host in _LOOPBACK):
        raise ValueError(f'{label} must use https (http allowed only on loopback): {scheme}://{host_part}')
    default_port = 443 if scheme == 'https' else 80
    origin = (f'{scheme}://{host_part}' if (port is None or port == default_port)
              else f'{scheme}://{host_part}:{port}')
    return f'{origin}{parsed.path.rstrip("/")}', origin


def resolve_urls(config: dict, fleet_url: str | None = None,
                 account_url: str | None = None) -> tuple[str, str, str, str]:
    site_target = str(config.get('site_host') or '').strip()
    site_host = site_target.rpartition('@')[2].strip()
    formatted = f'[{site_host}]' if ':' in site_host and not site_host.startswith('[') else site_host
    raw_fleet = (fleet_url or os.environ.get('ROSY_FLEET_URL', '')).strip()
    if not raw_fleet:
        if not formatted:
            raise ValueError('no Fleet URL configured (--fleet-url, ROSY_FLEET_URL, or lab-hosts.json site_host)')
        raw_fleet = f'https://{formatted}:8443'
    fleet_base, fleet_origin = _validate_url(raw_fleet, 'fleet URL')

    raw_acct = (account_url or os.environ.get('ROSY_ACCOUNT_URL', '')).strip()
    if not raw_acct:
        f_parsed = urllib.parse.urlsplit(fleet_base)
        acct_host = (f_parsed.hostname or '') or formatted
        if ':' in acct_host and not acct_host.startswith('['):
            acct_host = f'[{acct_host}]'
        raw_acct = f'{f_parsed.scheme}://{acct_host}'
    acct_base, acct_origin = _validate_url(raw_acct, 'account URL')
    return fleet_base, fleet_origin, acct_base, acct_origin


def _default_account_file() -> Path:
    local_app = os.environ.get('LOCALAPPDATA', '').strip()
    if local_app:
        return Path(local_app) / 'Rosy' / 'agent-operator-account.json'
    return Path.home() / '.config' / 'rosy' / 'agent-operator-account.json'


def _load_account(acct_path: Path, explicit: bool) -> tuple[str | None, object]:
    if not acct_path.is_file():
        if explicit:
            raise FileNotFoundError(f'account file not found: {acct_path}')
        return None, None
    data = json.loads(acct_path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or not str(data.get('login') or '').strip()
            or not isinstance(data.get('password'), str)):
        raise ValueError(f'account file missing login or password field ({acct_path})')
    return 'account', (str(data['login']).strip(), data['password'])


def resolve_auth(token_file: str | None = None,
                 account_file: str | None = None) -> tuple[str | None, object]:
    if token_file:
        path = Path(token_file).expanduser()
        tok = path.read_text(encoding='utf-8').strip()
        if not tok:
            raise ValueError(f'token file is empty: {path}')
        return 'bearer', tok
    if account_file:
        return _load_account(Path(account_file).expanduser(), explicit=True)
    env_tok = os.environ.get('ROSY_FLEET_TOKEN', '').strip()
    if env_tok:
        return 'bearer', env_tok
    env_acct = os.environ.get('ROSY_FLEET_ACCOUNT_FILE', '').strip()
    acct_path = Path(env_acct).expanduser() if env_acct else _default_account_file()
    return _load_account(acct_path, explicit=bool(env_acct))


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origins: set[str]):
        super().__init__()
        self.allowed_origins = allowed_origins

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        _, origin = _validate_url(resolved, 'redirect target', allow_query=True)
        if origin not in self.allowed_origins:
            if fp is not None:
                fp.close()
            raise ValueError(f'REDIRECT_OUTSIDE_TRUSTED_ORIGINS: {origin}')
        new_req = super().redirect_request(req, fp, code, msg, headers, resolved)
        if new_req is not None:
            _, src_origin = _validate_url(req.full_url, 'request URL', allow_query=True)
            if origin != src_origin:
                for hdrs in (new_req.headers, new_req.unredirected_hdrs):
                    for key in list(hdrs):
                        if key.lower() in ('authorization', 'origin'):
                            hdrs.pop(key, None)
        return new_req


def _read_limited(stream, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'response exceeded {limit} bytes')
    return raw


def _extract_error_code(err: urllib.error.HTTPError) -> str:
    try:
        raw = _read_limited(err, MAX_ERROR_BYTES)
        body = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
    except (OSError, ValueError):
        return ''
    if isinstance(body, dict):
        detail = body.get('detail')
        if isinstance(detail, dict) and isinstance(detail.get('code'), str):
            return detail['code']
        if isinstance(body.get('code'), str):
            return body['code']
    return ''


class _FleetApiClient:
    def __init__(self, fleet_base: str, fleet_origin: str, account_base: str, account_origin: str,
                 auth_kind: str, auth_cred: str | tuple[str, str], timeout_s: float = 30.0):
        self.fleet_base = fleet_base
        self.fleet_origin = fleet_origin
        self.account_base = account_base
        self.account_origin = account_origin
        self.timeout_s = timeout_s
        self._bearer = str(auth_cred) if auth_kind == 'bearer' else None
        jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(jar),
            _AllowedRedirectHandler({fleet_origin, account_origin}),
        )
        if auth_kind == 'account' and isinstance(auth_cred, tuple):
            login, acct_pw = auth_cred
            self._oauth_login(login, acct_pw)

    def _oauth_login(self, login: str, password: str) -> None:
        req = urllib.request.Request(
            f'{self.account_base}/api/fleet/auth/login',
            data=json.dumps({'login': login, 'password': password}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Origin': self.account_origin},
            method='POST',
        )
        with self._opener.open(req, timeout=self.timeout_s) as resp:
            _read_limited(resp, MAX_ERROR_BYTES)
        oauth_req = urllib.request.Request(
            f'{self.fleet_base}/api/fleet/auth/login?return=/console/maintenance',
            method='GET',
        )
        with self._opener.open(oauth_req, timeout=self.timeout_s) as resp:
            _read_limited(resp)
            final = urllib.parse.urlsplit(resp.geturl())
            _, final_origin = _validate_url(resp.geturl(), 'final URL', allow_query=True)
            if final_origin != self.fleet_origin or final.path.startswith('/console/login'):
                raise RuntimeError('Account OAuth login did not return to Fleet console')

    def request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {'Origin': self.fleet_origin}
        body = None
        if self._bearer is not None:
            headers['Authorization'] = f'Bearer {self._bearer}'
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(f'{self.fleet_base}{path}', data=body, headers=headers, method=method)
        with self._opener.open(req, timeout=self.timeout_s) as resp:
            raw = _read_limited(resp)
        parsed = json.loads(raw.decode('utf-8')) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError('unexpected non-object API response')
        return parsed


def _open_client(config: dict, *, fleet_url: str | None = None, account_url: str | None = None,
                 token_file: str | None = None, account_file: str | None = None) -> _FleetApiClient:
    kind, secret = resolve_auth(token_file=token_file, account_file=account_file)
    if kind is None:
        raise RuntimeError('no Fleet API credential found (set --token-file, ROSY_FLEET_TOKEN, or --account-file)')
    fleet_base, fleet_origin, acct_base, acct_origin = resolve_urls(config, fleet_url, account_url)
    return _FleetApiClient(fleet_base, fleet_origin, acct_base, acct_origin, kind, secret)


def status_api(config: dict, *, fleet_url: str | None = None, account_url: str | None = None,
               token_file: str | None = None, account_file: str | None = None,
               as_json: bool = False, out=None) -> int:
    stream = out or sys.stdout
    try:
        data = _open_client(config, fleet_url=fleet_url, account_url=account_url,
                            token_file=token_file, account_file=account_file).request_json('GET', '/api/fleet/hosts')
    except urllib.error.HTTPError as err:
        code = _extract_error_code(err)
        print(f'status failed: HTTP {err.code} {code}'.strip(), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as err:
        print(f'status failed: {err}', file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False), file=stream)
        return 0
    guard = data.get('guard') or {}
    for row in data.get('hosts', []):
        name = row.get('host', '?')
        actions = ','.join(row.get('actions') or ())
        g = guard.get(name) if isinstance(guard, dict) else None
        state = g.get('state', 'unknown') if isinstance(g, dict) else 'unknown'
        res = g.get('resources') if isinstance(g, dict) and isinstance(g.get('resources'), dict) else {}
        disk = res.get('disk') if isinstance(res.get('disk'), dict) else {}
        disk_s = (f"test={disk.get('test_free_gb')}GiB({disk.get('test_use_pct')}%) "
                  f"root={disk.get('root_free_gb')}GiB({disk.get('root_use_pct')}%)") if disk else 'disk=unknown'
        print(f"{name}: state={state} {disk_s} avail_ram={res.get('avail_pct', '?')}% actions=[{actions}]", file=stream)
    return 0


def run_api(host: str, action: str, unit: str | None, config: dict, *,
            fleet_url: str | None = None, account_url: str | None = None,
            token_file: str | None = None, account_file: str | None = None, out=None) -> int:
    control = _control()
    try:
        command = control.decide(host, action, unit, confirmed=True)
    except control.HostControlError as error:
        print(f'{host} {action}: {error.code}', file=sys.stderr)
        return 2
    try:
        client = _open_client(config, fleet_url=fleet_url, account_url=account_url,
                              token_file=token_file, account_file=account_file)
        data = client.request_json(
            'POST',
            f'/api/fleet/hosts/{urllib.parse.quote(command["host"], safe="")}/control',
            {'action': command['action'], 'unit': command['unit'], 'operator_confirmed': True},
        )
    except urllib.error.HTTPError as err:
        code = _extract_error_code(err)
        if code in _CODE_TO_EXIT:
            rc = _CODE_TO_EXIT[code]
            print(f'{host} {action}: {MEANING.get(rc, code)} ({code})', file=sys.stderr)
            return rc
        if code in _VALIDATION_CODES:
            print(f'{host} {action}: {code}', file=sys.stderr)
            return 2
        print(f'{host} {action}: HTTP {err.code} {code}'.strip(), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as err:
        print(f'{host} {action}: {err}', file=sys.stderr)
        return 1
    code = str(data.get('code') or 'ACCEPTED')
    print(f'{host} {action}: {code}', file=out or sys.stdout)
    return _CODE_TO_EXIT.get(code, 0)


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
    try:
        done = runner(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', target,
                       'sudo', '-n', HELPER, *command['argv']], check=False, timeout=60)
    except subprocess.TimeoutExpired:
        print(f'{host} {action}: no answer in 60 s; the result is unknown, check the PC', file=sys.stderr)
        return 1
    if done.returncode:
        msg = MEANING.get(done.returncode, f"failed with exit {done.returncode}")
        print(f'{host} {action}: {msg}', file=sys.stderr)
    return done.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('host')
    parser.add_argument('action', nargs='?')
    parser.add_argument('unit', nargs='?')
    parser.add_argument('--confirm', help='the host name again: these actions are hard to take back')
    parser.add_argument('--via-api', action='store_true', help='send through Fleet HTTPS API (default when configured)')
    parser.add_argument('--via-ssh', action='store_true', help='send directly over SSH instead of Fleet HTTPS API')
    parser.add_argument('--json', action='store_true', help='for status: print raw /api/fleet/hosts JSON')
    parser.add_argument('--fleet-url', help='override Fleet base URL')
    parser.add_argument('--account-url', help='override Account base URL')
    parser.add_argument('--token-file', help='path to Fleet operator bearer token')
    parser.add_argument('--account-file', help='path to Account operator login JSON')
    args = parser.parse_args(argv)
    if args.via_api and args.via_ssh:
        parser.error('choose at most one of --via-api and --via-ssh')
    if args.host == 'list':
        for row in _control().catalogue()['hosts']:
            print(row['host'], ' '.join(row['actions']), *row['units'])
        return 0
    if args.host != 'status' and (not args.action or args.confirm != args.host):
        parser.error('give an action and --confirm <host>')
    config = lab_hosts.load()
    api_kw = dict(fleet_url=args.fleet_url, account_url=args.account_url,
                  token_file=args.token_file, account_file=args.account_file)
    if args.host == 'status':
        return status_api(config, as_json=args.json, **api_kw)
    if not args.via_ssh:
        use_api = args.via_api
        if not use_api:
            try:
                auth_kind, _ = resolve_auth(token_file=args.token_file, account_file=args.account_file)
            except (OSError, ValueError) as err:
                if args.token_file or args.account_file:
                    print(f'{args.host} {args.action}: {err}', file=sys.stderr)
                    return 1
                auth_kind = None
            raw_url = args.fleet_url or os.environ.get('ROSY_FLEET_URL', '') or config.get('site_host', '')
            use_api = auth_kind is not None and bool(str(raw_url).strip())
        if use_api:
            return run_api(args.host, args.action, args.unit, config, **api_kw)
    return run(args.host, args.action, args.unit, config)


if __name__ == '__main__':
    raise SystemExit(main())
