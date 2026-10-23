"""Show every lab PC's update channel at a glance; read-only (D-805).

    python tools/remote/update_status.py

For each host in private/lab-hosts.json, this reads the freeze gate, every rosy user
update unit (`*autoupdate*`, `*-update`), its last JSON step and result, and the rosy units
systemd lists as failed. A channel is `STUCK` when its unit failed or it logged no healthy step
(switched, up_to_date, idle, active) within `--stale-hours` (default 6); a disabled timer is `OFF`.
Exit 1 when any channel is STUCK or a host is unreachable. Nothing is started, stopped or changed.
"""
from __future__ import annotations

import argparse
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
  log=$(journalctl --user -u "$u" --no-pager -n 400 -o short-unix 2>/dev/null | grep '{')
  healthy=$(printf '%s\n' "$log" | grep -E '"(step|result)": "(switched|up_to_date|idle|active)"' | tail -1 | cut -d' ' -f1)
  echo "unit $u $result $timer ${healthy:--} $(printf '%s\n' "$log" | tail -1)"
done
for f in $(systemctl --user --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | grep '^rosy-'); do echo "failed $f"; done
'''
HEALTHY = {'switched', 'up_to_date', 'idle', 'active'}


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None


def parse(text: str, now: float, stale_hours: float) -> dict:
    """One host's probe output -> channels; a channel is STUCK when it has not been healthy recently.

    A short deferral (a running job, waiting for CI) is normal; the same deferral for longer than
    `stale_hours` is what hid the field PC (4 days) and AI PC (3 days) stalls in October.
    """
    host = dict(gate='unknown', channels=[], failed=[])
    for raw in text.splitlines():
        kind, _, rest = raw.partition(' ')
        if kind == 'gate':
            host['gate'] = rest.strip()
        elif kind == 'failed':
            host['failed'].append(rest.strip())
        elif kind == 'unit':
            fields = rest.split(' ', 5)
            unit, result, timer, healthy = (fields + ['', '', '', ''])[:4]
            last = fields[5] if len(fields) > 5 else ''
            step = {}
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stale-hours', type=float, default=6.0)
    args = parser.parse_args()
    head = subprocess.run(['git', 'rev-parse', '--short=12', 'origin/main'], capture_output=True, text=True).stdout.strip()
    print(f'origin/main {head or "unknown (git fetch first)"}')
    stuck = False
    for target in dict.fromkeys(lab_hosts.test_hosts() + [lab_hosts.site_host()]):
        if not target:
            continue
        # bytes, not text: Windows text mode would send CRLF into bash
        done = subprocess.run([*SSH, '--', target, 'bash -s'], input=PROBE.encode(), capture_output=True, timeout=90)
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
    sys.exit(1 if stuck else 0)


if __name__ == '__main__':
    main()
