"""Prepare an expiring workspace on a lab test host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

import lab_hosts
import remote_job
import remote_pytest as rp

SOURCE_HOURS = 72
TEMP_HOURS = 48
LABEL = r"[a-z0-9][a-z0-9-]{0,31}"
CREATE = r"""set -euo pipefail
umask 077
store=$HOME/rosy-test; root=$store/studies
[ ! -e "$HOME/rosy-jobs/site" ] || { echo "refusing site host" >&2; exit 1; }
[ ! -L "$store" ] && [ ! -L "$root" ] || { echo "refusing linked scratch root" >&2; exit 1; }
grep -Fxq 'TEST_WORKSPACE_RETENTION = 1' "$store/maintenance/host_storage.py" 2>/dev/null ||
  { echo "test-workspace retention support is not deployed on this host" >&2; exit 1; }
mkdir -p -- "$root"
workspace=$(mktemp -d -- "$root/test-$1-XXXXXX")
marker=$workspace/.rosy-retention.json
trap 'if [ ! -f "$marker" ]; then rm -f -- "$marker.tmp"; rmdir -- "$workspace"; fi' EXIT
expires=$(($(date +%s) + $2))
printf '%s,"expires":%s}\n' "${3%?}" "$expires" > "$marker.tmp"
mv -T -- "$marker.tmp" "$marker"
# The marker survives an interrupted archive transfer.
if [ "$4" = source ]; then
  mkdir -- "$workspace/src"
  tar -xf - --no-same-owner --no-same-permissions -C "$workspace/src"
fi
printf 'ROSYWORKSPACE %s\t%s\n' "$workspace" "$expires"
"""


def metadata(owner: str, reason: str, commit: str | None = None) -> str:
    data = {"schema": "rosy.test-workspace-retention/1", "owner": owner, "reason": reason}
    if commit is not None:
        data["source_sha"] = commit
    return json.dumps(data, separators=(",", ":"))


def choose_host(target: str | None) -> str:
    sites = rp.SITES | {lab_hosts.site_host()}
    hosts = [lab_hosts.ssh_target(h, "test_hosts") for h in lab_hosts.test_hosts() if h not in sites]
    if target is not None:
        if target not in hosts:
            raise SystemExit("choose a configured non-site test host")
        hosts = [target]
    eligible = [h for h in rp.placed_hosts("pytest", hosts) if h not in rp.SITES]
    if not eligible:
        raise SystemExit("no eligible lab host for a test workspace")
    return eligible[0]


def receipt(host: str, output: bytes) -> dict:
    records = re.findall(rb"^ROSYWORKSPACE ([^\r\n\t]+)\t([0-9]+)\r?$", output, re.MULTILINE)
    if len(records) == 1:
        path, expiry = records[0]
        remote_path = PurePosixPath(path.decode())
        if (remote_path.is_absolute() and ".." not in remote_path.parts
                and remote_path.parent.parts[-2:] == ("rosy-test", "studies")
                and re.fullmatch(rf"test-{LABEL}-[a-zA-Z0-9]{{6}}", remote_path.name)
                and int(expiry) >= 1_600_000_000):
            return {"host": host, "path": str(remote_path), "expires": int(expiry)}
    raise SystemExit("test host did not confirm the managed workspace")


def prepare(host: str, repo: Path, label: str, owner: str, reason: str, commit: str | None) -> dict:
    hours = SOURCE_HOURS if commit else TEMP_HOURS
    args = (label, str(hours * 3600), metadata(owner, reason, commit), "source" if commit else "temp")
    if commit is None:
        result = rp.remote(host, CREATE, *args, timeout=30, capture_output=True)
        result.check_returncode()
    else:
        command = remote_job.argv_command(CREATE, args, rp.capped(host))
        with subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", commit],
                              stdout=subprocess.PIPE) as archive:
            try:
                result = remote_job.step([*rp.SSH, host, command], stdin=archive.stdout, capture_output=True,
                                         timeout=rp.STEP_TIMEOUT["ship"])
                result.check_returncode()
                archive.stdout.close()
                if archive.wait(timeout=10):
                    raise SystemExit("could not archive the committed source")
            finally:
                if archive.poll() is None:
                    archive.kill()
    return receipt(host, result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="lowercase label, up to 32 characters")
    parser.add_argument("--owner", required=True, help="person or session responsible for the workspace")
    parser.add_argument("--reason", required=True, help="purpose recorded in the retention marker")
    parser.add_argument("--sha", help="committed revision to put in src/ (omit for an empty workspace)")
    parser.add_argument("--host", help="one configured non-site lab test host")
    args = parser.parse_args(argv)
    owner, reason = args.owner.strip(), args.reason.strip()
    if not re.fullmatch(LABEL, args.label) or not owner or not reason:
        parser.error("use a lowercase alphanumeric/hyphen label and a nonblank owner and reason")
    repo = Path(__file__).resolve().parents[2]
    try:
        commit = rp.git(repo, "rev-parse", "--verify", "--end-of-options", f"{args.sha}^{{commit}}") if args.sha else None
        if commit and rp.git(repo, "ls-tree", commit, "--", "private"):
            parser.error("the chosen commit contains files under private/")
        if len(metadata(owner, reason, commit)) > 65536 - 32:  # reserve room for the host's expires field
            parser.error("the workspace retention marker is too large")
        print(json.dumps(prepare(choose_host(args.host), repo, args.label, owner, reason, commit)))
    except subprocess.CalledProcessError as error:
        details = (error.stderr or b"").decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        raise SystemExit(f"test workspace preparation failed (exit {error.returncode})"
                         f"{': ' + details.strip() if details else ''}") from error
    except subprocess.TimeoutExpired as error:
        raise SystemExit("test workspace preparation timed out") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
