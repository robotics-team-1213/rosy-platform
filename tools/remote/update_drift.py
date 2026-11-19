"""Drift checks for update_status (D-1021): retired names, receiver keys, R's guard timer.

Everything here is read-only and prints names, never key material or file content. The probe text is appended to
update_status.PROBE; the parsers and checks are pure so tests feed them fixtures.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

# Appended after update_status.PROBE (which defines $D). One line per fact; unreadable files become `-unreadable` lines.
PROBE = r'''
# Unrecorded image changes are not compared here: the candidate records archive image IDs in another form than
# `docker inspect` shows (2026-11-14: a naive compare failed every service). The site updater's own verifier does
# it and its refusal reason reaches update_status through site-autoupdate.json (`last run refused: ...`).
# receiver pins: issuer and the key names (kid) only, never key material
for f in $(find ~/.config/rosy -maxdepth 5 -type f -name receiver.json 2>/dev/null) /etc/rosy/*/receiver.json /etc/rosy/fleet-account/client.json; do
  [ -L "$f" ] && continue
  case "$f" in *.bak*|*backup*|*before-*|*.orig*|*rosy-backup*|*rosy-source-repair*) continue;; esac
  [ -e "$f" ] || sudo -n test -e "$f" </dev/null 2>/dev/null || continue
  out=$({ cat "$f" 2>/dev/null || sudo -n cat "$f" 2>/dev/null; } </dev/null | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(json.dumps({"issuer":d.get("issuer"),"kids":sorted(d.get("public_key_files") or {})}))' 2>/dev/null)
  [ -n "$out" ] && echo "receiver $f $out" || echo "receiver-unreadable $f"
done
# chrony `server` names, compared with the site map's time_source (the usable count is update_status's chrony line)
if command -v chronyc >/dev/null 2>&1; then
  echo "chrony-servers $(cat /etc/chrony/chrony.conf /etc/chrony/conf.d/*.conf /etc/chrony/sources.d/*.sources /etc/chrony.conf 2>/dev/null </dev/null | awk '$1=="server"{print tolower($2)}' | sort -u | tr '\n' ' ')"
fi
# R's host guard: its timer and when it last wrote status.json
if systemctl cat rosy-host-guard.timer >/dev/null 2>&1; then
  gs=/var/lib/rosy-host-guard/status.json
  echo "guard $(systemctl is-active rosy-host-guard.timer 2>/dev/null) $(stat -c %Y "$gs" 2>/dev/null || sudo -n stat -c %Y "$gs" 2>/dev/null </dev/null || echo -)"
else
  echo "guard none"
fi
true
'''
GUARD_STALE_S = 30 * 60  # the guard runs every 10 minutes; three missed runs
_ISSUER = re.compile(r'https://[A-Za-z0-9._\[\]:-]+')  # the Account protocol requires an HTTPS issuer


def retired_hostnames(path: Path | None = None) -> tuple[list[str], str]:
    """Retired names from the private site map (``retired_hostnames:`` list of {name, retired, note}); (names, note)."""
    import site_map
    path = path or site_map.map_file()
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return [], f'retired-name scan skipped: private site map {path.name} is missing or unreadable'
    rows = data.get('retired_hostnames') if isinstance(data, dict) else None
    if not rows:
        return [], f'retired-name scan skipped: no retired_hostnames in {path.name}'
    if not isinstance(rows, list):
        raise SystemExit(f'{path}: retired_hostnames must be a list of {{name, retired, note}}')
    names = [row.get('name') if isinstance(row, dict) else row for row in rows]
    for name in names:  # a short or dotless entry would match unrelated text in every config file
        if not isinstance(name, str) or len(name) < 8 or '.' not in name:
            raise SystemExit(f'{path}: retired_hostnames entry {name!r} must be a full hostname (8+ characters with a dot)')
    return names, ''


def expected_time_source(target: str):
    """(site map host name, expected chrony server names) for an ssh target; None when the map is missing or has none.

    A missing map is already noted once by retired_hostnames; a malformed one stops the run (site_map.load)."""
    import site_map
    try:
        site = site_map.load()
    except OSError:
        return None
    found = site_map.host_for(site, target)
    names = site_map.time_source(site, found[1]) if found else None
    return (found[0], names) if names else None


def time_source_gap(targets) -> str:
    """One note naming the targets whose chrony names cannot be compared (no site map, the map's ssh: texts do not name
    the target, or no time_source for it); '' when all can. The compare must never vanish silently."""
    missing = [t for t in targets if expected_time_source(t) is None]
    return (f'time-source compare skipped for {", ".join(missing)} (no site map, not named in its ssh: texts, or no time_source)'
            if missing else '')


def parse(host: dict, kind: str, rest: str) -> bool:
    """Take one probe line of this module's kinds into ``host``; False when the kind is not ours."""
    if kind == 'receiver':
        path, _, raw = rest.strip().partition(' ')
        try:
            pin = json.loads(raw)
            if not isinstance(pin, dict) or not isinstance(pin.get('kids'), list):
                raise ValueError
        except ValueError:
            host.setdefault('receivers_unreadable', []).append(path)
        else:
            host.setdefault('receivers', []).append((path, pin))
    elif kind == 'receiver-unreadable':
        host.setdefault('receivers_unreadable', []).append(rest.strip())
    elif kind == 'chrony-servers':
        host['chrony_servers'] = set(rest.split())
    elif kind == 'guard':
        fields = rest.split()
        host['guard'] = dict(active=fields[0] if fields else 'none', written=float(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None)
    else:
        return False
    return True


def fetch_kids(ssh_command: list[str], issuer: str) -> set[str] | None:
    """kid names the issuer publishes at /api/fleet/auth/keys, fetched with curl from the site host; None if unreachable."""
    import shlex
    try:
        done = subprocess.run([*ssh_command, f'curl -fsS --max-time 10 {shlex.quote(issuer + "/api/fleet/auth/keys")}'],
                              capture_output=True, timeout=40)
        keys = json.loads(done.stdout.decode()).get('keys') if done.returncode == 0 else None
        return {k['kid'] for k in keys if isinstance(k, dict) and isinstance(k.get('kid'), str)} if isinstance(keys, list) else None
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None


class IssuerKeys:
    """Callable issuer -> kid set, fetched once per issuer from the site host (None: no site host or unreachable)."""

    def __init__(self, ssh_command):
        self.ssh, self.cache = ssh_command, {}

    def __call__(self, issuer):
        if issuer not in self.cache:
            self.cache[issuer] = fetch_kids(self.ssh, issuer) if self.ssh else None
        return self.cache[issuer]


def findings(host: dict, roles, now: float, issuer_kids, time_source=None) -> list:
    """(verdict, name, detail): receiver key drift, guard liveness, time source. ``issuer_kids(issuer)`` -> set or None."""
    out = []
    if time_source and host.get('chrony_servers') is not None:
        import site_map
        mismatch = site_map.time_mismatch(host['chrony_servers'], time_source[1])
        if mismatch:
            out.append(('FAIL', f'time-source {time_source[0]}', mismatch))
    for path in host.get('receivers_unreadable', []):
        out.append(('note', 'account-key-drift', f'{path} could not be read; not checked'))
    unreachable, keyless = set(), set()
    for path, pin in host.get('receivers', []):
        issuer = (pin.get('issuer') or '').rstrip('/') if isinstance(pin.get('issuer'), str) else ''
        if not _ISSUER.fullmatch(issuer):
            out.append(('FAIL', 'account-key-drift', f'{path} has no https issuer'))
            continue
        current = issuer_kids(issuer)
        if current is None:
            unreachable.add(issuer)
        elif not current:  # the issuer itself is broken; blaming every receiver would send people the wrong way
            keyless.add(issuer)
        elif not current.intersection(pin['kids']):
            out.append(('FAIL', 'account-key-drift', path))
    # A key check that could not run must not read as clean (2026-11-14 panel): a rotated key would pass silently.
    out += [('FAIL', 'account-key-drift', 'issuer keys could not be fetched from the site host; receivers not compared') for _ in unreachable][:1]
    out += [('FAIL', 'account-key-drift', f'{issuer} publishes no keys') for issuer in sorted(keyless)]
    guard = host.get('guard')
    if 'site' in roles:
        if guard is None or guard['active'] == 'none':
            out.append(('FAIL', 'host-guard', 'rosy-host-guard.timer is not installed on the site host'))
        elif guard['active'] != 'active':
            out.append(('FAIL', 'host-guard', f'rosy-host-guard.timer is {guard["active"]}'))
        elif guard['written'] is None:
            out.append(('note', 'host-guard', 'the guard status.json time could not be read'))
        elif now - guard['written'] > GUARD_STALE_S:
            out.append(('FAIL', 'host-guard', f'status.json last written {(now - guard["written"]) / 60:.0f} min ago'))
    return out
