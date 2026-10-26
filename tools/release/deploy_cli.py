"""Operator entrypoint for native and SDK-host deployment target selection."""

import argparse
import json
import sys

from deployment_targets import DeploymentError, dispatch, load_targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for name in ("plan", "apply", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--robot", required=True)
        command.add_argument("--public-key")
        if name == "plan":
            command.add_argument("--operation", choices=("apply", "rollback"), required=True)
        if name != "rollback":
            command.add_argument("--tarball")
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list(load_targets().values())
        else:
            result = dispatch(args.target, args.operation if args.command == "plan" else args.command,
                              args.robot, tarball=getattr(args, "tarball", None),
                              public_key=args.public_key, execute=args.command != "plan")
        print(json.dumps(result, ensure_ascii=False))
        return result.get("returncode", 0) if isinstance(result, dict) else 0
    except DeploymentError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
