"""Deliver an intake-passed model to a robot's shadow slot (D-356).

deliver.py push <host> <model_revision> [--user pinky] [--models data/perception/models]
deliver.py rollback <host>
deliver.py status <host>

push: scp to /var/lib/rosy/models/<rev>.partial, sha256sum -c on the robot,
mv to <rev>, then an atomic pointer swap (shadow.tmp -> shadow; the old value
stays in shadow.previous). The pointer holds the model folder path that
ModelSlot reads. Model files are a data generation, not a release payload."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SENSING = ROOT / "src" / "runtime" / "sensing"
if str(_SENSING) not in sys.path:
    sys.path.insert(0, str(_SENSING))

from control.sensing.perception.learned.manifest import (  # noqa: E402
    ManifestError, load_manifest, verify_files)

REMOTE_ROOT = "/var/lib/rosy/models"
_SAFE_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def remote_script(action: str, rev: str | None, root: str = REMOTE_ROOT, *,
                  checks=()) -> str:
    """Shell text for one remote step. Every path is shlex.quote'd.

    checks: [(sha256, file name), ...] from the manifest, verified before install."""
    q = shlex.quote
    ptr, prev, tmp = q(f"{root}/shadow"), q(f"{root}/shadow.previous"), q(f"{root}/shadow.tmp")
    if action == "prepare":
        return f"set -e; mkdir -p {q(root)}; rm -rf {q(f'{root}/{rev}.partial')}"
    if action == "push":
        if not checks:
            raise ValueError("push needs manifest checks")
        partial, final = q(f"{root}/{rev}.partial"), q(f"{root}/{rev}")
        sums = " ".join(q(f"{sha}  {name}") for sha, name in checks)
        return "\n".join([
            "set -e",
            f"cd {partial}",
            f"printf '%s\\n' {sums} | sha256sum -c -",
            "cd /",
            f"if [ -d {final} ]; then rm -rf {partial}; else mv {partial} {final}; fi",
            f"cp {ptr} {prev} 2>/dev/null || true",
            f"printf %s {final} > {tmp} && mv {tmp} {ptr}",
        ])
    if action == "rollback":
        return "\n".join([
            "set -e",
            f"[ -f {prev} ] || {{ echo 'no shadow.previous to roll back to' >&2; exit 1; }}",
            f"mv {prev} {ptr}",
        ])
    if action == "status":
        return "\n".join([
            f"echo \"shadow: $(cat {ptr} 2>/dev/null)\"",
            f"echo \"previous: $(cat {prev} 2>/dev/null)\"",
            f"ls -1 {q(root)} 2>/dev/null || true",
        ])
    raise ValueError(f"unknown action {action!r}")


def _run(runner, cmd) -> bool:
    r = runner(cmd, check=False, capture_output=True, text=True)
    if getattr(r, "stdout", None):
        print(r.stdout, end="")
    if r.returncode != 0:
        print(f"failed ({r.returncode}): {' '.join(cmd[:2])} {getattr(r, 'stderr', '')}",
              file=sys.stderr)
        return False
    return True


def _push(args, runner) -> int:
    rev = args.revision
    if not _SAFE_REV.match(rev):
        print(f"refused: unsafe revision {rev!r}", file=sys.stderr)
        return 2
    folder = Path(args.models) / rev
    try:
        report = json.loads((folder / "intake_report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"refused: no readable intake report: {exc}", file=sys.stderr)
        return 2
    if report.get("verdict") != "pass" or report.get("model_revision") != rev:
        print(f"refused: intake verdict {report.get('verdict')!r} for {rev}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(folder)
        verify_files(manifest)
    except ManifestError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if manifest.model_revision != rev:
        print(f"refused: manifest revision {manifest.model_revision} != {rev}", file=sys.stderr)
        return 2
    target = f"{args.user}@{args.host}"
    checks = [(f.sha256, f.name) for f in manifest.files]
    steps = [
        ["ssh", target, remote_script("prepare", rev, args.root)],
        ["scp", "-r", str(folder), f"{target}:{args.root}/{rev}.partial"],
        ["ssh", target, remote_script("push", rev, args.root, checks=checks)],
    ]
    for cmd in steps:
        if not _run(runner, cmd):
            return 1
    print(f"shadow -> {args.root}/{rev} on {args.host}")
    return 0


def main(argv=None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("push", "rollback", "status"):
        p = sub.add_parser(name)
        p.add_argument("host")
        if name == "push":
            p.add_argument("revision")
            p.add_argument("--models", default=str(ROOT / "data" / "perception" / "models"))
        p.add_argument("--user", default="pinky")
        p.add_argument("--root", default=REMOTE_ROOT)
    args = ap.parse_args(argv)
    if args.action == "push":
        return _push(args, runner)
    ok = _run(runner, ["ssh", f"{args.user}@{args.host}",
                       remote_script(args.action, None, args.root)])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
