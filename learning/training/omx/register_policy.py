"""Propose a finished offline ACT cycle as an L0 policy on Fleet (D-793).

L0 grants no execution: it only records that this exact model exists, bound to its cycle
receipt hash, rig and calibration revisions. A policy administrator still decides the proposal on
/console/policy, and every later stage needs its own approval.

    python register_policy.py --cycle <run-dir> --fleet https://<site>:8443 --workcell <id> --dry-run
    ROSY_FLEET_TOKEN=... python register_policy.py --cycle <run-dir> --fleet ... --workcell <id> --confirm

The bearer token is read from the environment only, never from arguments.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
from urllib import error, parse, request

_ID = re.compile(r'^[A-Za-z0-9._:@/-]{1,128}$')
_WORKCELL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def proposal(cycle_dir):
    """The L0 proposal body for a finished cycle; refuses anything that is not offline-only."""
    path = Path(cycle_dir) / 'cycle-receipt.json'
    raw = path.read_bytes()
    receipt = json.loads(raw)
    if (receipt.get('offline_only') is not True or receipt.get('device_execution') is not False
            or receipt.get('promotion') is not False):
        raise ValueError('only an offline, unpromoted cycle receipt can be proposed as L0')
    for key in ('policy_revision', 'rig_revision', 'calibration_revision'):
        if not isinstance(receipt.get(key), str) or not _ID.fullmatch(receipt[key]):
            raise ValueError(f'cycle receipt has no valid {key}; rerun the cycle with this tool version')
    evaluation = receipt.get('evaluation') or {}
    mae = evaluation.get('mae', evaluation.get('eval_mae'))
    note = (f"ACT offline cycle, source {receipt.get('source_mode')}, split {receipt.get('split_receipt_sha256', '')[:12]}"
            + (f", eval MAE {mae}" if isinstance(mae, (int, float)) else ''))
    return dict(operator_confirmed=True, policy_revision=receipt['policy_revision'], to_stage='L0',
                rig_revision=receipt['rig_revision'], calibration_revision=receipt['calibration_revision'],
                evidence_sha256=hashlib.sha256(raw).hexdigest(), note=note[:500])


def submit(fleet, workcell, body, token, *, ca=None, opener=request.urlopen):
    if not _WORKCELL.fullmatch(workcell):
        raise ValueError('invalid workcell id')
    url = f"{fleet.rstrip('/')}/api/fleet/workcells/{parse.quote(workcell, safe='')}/policy/proposals"
    if parse.urlsplit(url).scheme not in ('https', 'http'):
        raise ValueError('Fleet URL must be http(s)')
    req = request.Request(url, data=json.dumps(body).encode(), method='POST', headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'})
    context = ssl.create_default_context(cafile=ca) if ca else None
    try:
        with opener(req, timeout=20, context=context) as response:
            return json.loads(response.read())
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise SystemExit(f'Fleet refused the proposal ({exc.code}): {detail}') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cycle', type=Path, required=True, help='native_cycle run directory')
    parser.add_argument('--fleet', required=True, help='Fleet base URL')
    parser.add_argument('--workcell', required=True)
    parser.add_argument('--ca', help='CA bundle for the site certificate')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='print the proposal, send nothing')
    mode.add_argument('--confirm', action='store_true', help='send the L0 proposal')
    args = parser.parse_args(argv)
    body = proposal(args.cycle)
    if args.dry_run:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    token = os.environ.get('ROSY_FLEET_TOKEN', '')
    if not token.strip():
        raise SystemExit('ROSY_FLEET_TOKEN is required (a policy-admin or policy_admin operator token)')
    print(json.dumps(submit(args.fleet, args.workcell, body, token, ca=args.ca), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
