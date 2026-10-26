"""Publish an explicit monitor output file; never open a motor bus or issue commands."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import time
from urllib.parse import quote
from urllib.request import HTTPSHandler, Request, build_opener

from deploy.robot.omx.workcell_observation_bridge import _NoRedirect, _verified, secure_url


def publish(raw, *, fleet_url, device_id, source_id, token, context, opener=None):
    origin = secure_url(fleet_url, 'https')
    _verified(context)
    if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('explicit source credential required')
    if len(raw) > 65536:
        raise ValueError('report exceeds ingress limit')
    report = json.loads(raw)
    if not isinstance(report, dict) or report.get('schema') != 'rosy.omx-load-monitor.v1':
        raise ValueError('expected monitor output')
    url = origin + '/api/fleet/device-profiles/' + quote(device_id, safe='') + '/load-reports/' + quote(source_id, safe='')
    request = Request(url, data=raw, method='POST', headers={
        'Content-Type': 'application/json', 'X-Workcell-Observation-Token': token})
    transport = opener or build_opener(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with transport.open(request, timeout=2) as response:
        if response.status != 202:
            raise ValueError('report was not accepted')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--fleet-url', required=True)
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--token-env', required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    context = ssl.create_default_context(cafile=args.ca_file)
    token = os.environ.get(args.token_env)
    secure_url(args.fleet_url, 'https')
    if not token:
        parser.error('source credential environment variable is empty')
    previous = None
    while True:
        try:
            if args.report.is_symlink() or not args.report.is_file():
                raise ValueError('expected regular monitor output file')
            with args.report.open('rb') as handle:
                raw = handle.read(65537)
            if raw != previous:
                publish(raw, fleet_url=args.fleet_url, device_id=args.device_id, source_id=args.source_id,
                        token=token, context=context)
                previous = raw
            if args.once:
                return 0
            time.sleep(0.1)
        except (OSError, ValueError, RecursionError):
            print('Load report delivery unavailable; source times preserved.', file=sys.stderr)
            if args.once:
                return 1
            time.sleep(1)


if __name__ == '__main__':
    raise SystemExit(main())
