#!/usr/bin/env python3
"""Root code issuer and unprivileged HTTPS recovery entrypoint."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_launcher import eligible, issue, run_frontend

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('eligible', 'issue', 'serve'))
    parser.add_argument('--renew', action='store_true')
    args = parser.parse_args()
    if args.command == 'eligible':
        raise SystemExit(0 if eligible() else 1)
    if args.command == 'issue':
        issue(renew=args.renew)
    else:
        run_frontend()
