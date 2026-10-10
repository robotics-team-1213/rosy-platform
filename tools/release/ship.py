"""Reserve, build, sign and push a delta release to several robots in one command (D-553 addendum 4).

    python tools/release/ship.py --base <base-id> --robots 9dfk,8kcn

1. Starts each robot's calibration guard (rosy-calibration-guard.ps1) in the background.
2. Reserves the next release id with the payload-reserved-<id> tag robot_cd.py uses
   (or takes --release-id).
3. Builds the signed delta on X:/DevTemp/rosy-release-<base>/x/<base> with
   make_delta_release.py (metadata only, ~5 s).
4. Picks the restart scope: "camera" when every changed payload file is camera
   perception code (CAMERA_ONLY) -- the robot then restarts rosy-camera alone and
   CORE keeps running; otherwise "full" (activate-release.sh, CORE release check,
   CORE readiness), as rosy-release-push.ps1 does. The image-layer sync runs only
   when the delta changes a deploy/robot/native file.
5. Pushes to every robot at once, one ssh session each (ship_remote.sh), and
   prints one summary. Logs: X:/DevTemp/rosy-release-<id>/ship-<robot>.txt.

Signatures, the robot's full-tree verify (native_release.py) and its rollback on a
failed start are unchanged. --dry-run builds into X:/DevTemp/fast-ship-dry and
prints the plan without reserving, guarding or pushing. Full builds and rollbacks
still go through rosy-release-push(-many).ps1.
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PINKY = ROOT / "deploy" / "robot" / "pinky_pro"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_delta_release  # noqa: E402
from robot_cd import RELEASE, next_release_id  # noqa: E402

REPO = "robotics-team-1213/rosy-platform"
ROBOTS = {"9dfk": "192.168.1.201", "8kcn": "192.168.1.202"}
CONTROL = "install/lib/python3.12/site-packages/control/"
# Loaded only by rosy-camera's camera_preview.launch.py nodes. control/sensing/__init__
# and ir_adc_node (rosy-io) never import perception/ (test_ship.py pins that); CORE
# never imports control at all.
CAMERA_ONLY = (CONTROL + "sensing/perception/",) + tuple(
    f"{CONTROL}{name}.py" for name in ("line_observer_node", "road_observer_node", "learned_lane_node",
                                       "camera_detect_node", "object_detector_node", "capture_trigger_node",
                                       "pilot_recorder_node"))
METADATA = {"manifest.json", "SHA256SUMS", "SHA256SUMS.sig", *make_delta_release.GENERATED}
IMAGE_LAYER = "deploy/robot/native/"


def scope(changed: list[str]) -> tuple[str, bool]:
    """(restart mode, image-layer sync needed) for the payload paths a delta replaces."""
    payload = [p for p in changed if p not in METADATA]
    camera = bool(payload) and all(p.startswith(CAMERA_ONLY) for p in payload)
    return ("camera" if camera else "full"), any(p.startswith(IMAGE_LAYER) for p in payload)


def reserve() -> str:
    """Next free id, reserved with GitHub's atomic tag creation (robot_cd.py's rule)."""
    tags = subprocess.run(["git", "-C", str(ROOT), "ls-remote", "--tags", "origin", "refs/tags/payload-*"],
                          check=True, capture_output=True, text=True).stdout
    names = [line.rsplit("/", 1)[-1] for line in tags.splitlines()]
    names += [p.name.removeprefix("rosy-release-") for p in Path("X:/DevTemp").glob("rosy-release-*")]
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "origin/main"],
                         check=True, capture_output=True, text=True).stdout.strip()
    for _ in range(5):
        release_id = next_release_id(datetime.now(timezone.utc).strftime("%Y.%m.%d"), names)
        made = subprocess.run(["gh", "api", "--method", "POST", f"repos/{REPO}/git/refs",
                               "-f", f"ref=refs/tags/payload-reserved-{release_id}", "-f", f"sha={sha}"],
                              capture_output=True, text=True)
        if made.returncode == 0:
            return release_id
        if "already exists" not in made.stdout + made.stderr:
            raise RuntimeError(f"reserving {release_id} failed: {made.stderr.strip() or made.stdout.strip()}")
        names.append(release_id)
    raise RuntimeError("no free release id after 5 tries")


def remote_stdin(release_id: str, base_id: str, tarball: Path, mode: str, sync: bool, holder: str) -> bytes:
    """One bash program: unpack the helper and the tarball into a root scratch dir, run, clean up."""
    def blob(name: str, data: bytes) -> str:
        return f"base64 -d > \"$W/{name}\" <<'ROSY_B64'\n{base64.encodebytes(data).decode()}ROSY_B64\n"
    return ("set -u\nW=$(mktemp -d /var/tmp/rosy-ship.XXXXXX) || exit 1\n"
            + blob("rosy-release-unpack.sh", (PINKY / "native" / "rosy-release-unpack.sh").read_bytes())
            + blob("ship_remote.sh", (Path(__file__).resolve().parent / "ship_remote.sh").read_bytes())
            + blob(f"{release_id}.tar.gz", tarball.read_bytes())
            + f'bash "$W/ship_remote.sh" "$W" {release_id} {base_id} {mode} {int(sync)} {holder} </dev/null\n'
            + 'rc=$?; rm -rf -- "$W"; exit $rc\n').encode()


def ssh_argv(ip: str) -> list[str]:
    local = Path(os.environ["LOCALAPPDATA"]) / "Rosy"
    return ["ssh", "-i", str(local / "ssh" / "rosy-operator-ed25519"), "-o", f"UserKnownHostsFile={local / 'known_hosts'}",
            "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=10", f"rosy@{ip}", "sudo", "-n", "bash", "-s"]


def guard(ip: str) -> subprocess.Popen:
    return subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(PINKY / "rosy-calibration-guard.ps1"), "-Robot", ip, "-Action", "a fast ship"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def push(name: str, ip: str, guard_run: subprocess.Popen, stdin: bytes, log: Path) -> tuple[str, bool, str]:
    started = time.monotonic()
    guard_out, _ = guard_run.communicate()
    if guard_run.returncode != 0:
        log.write_text(guard_out, encoding="utf-8")
        return name, False, f"calibration guard refused (exit {guard_run.returncode}); see {log}"
    run = subprocess.run(ssh_argv(ip), input=stdin, capture_output=True, timeout=600)
    text = guard_out + run.stdout.decode(errors="replace") + run.stderr.decode(errors="replace")
    log.write_text(text, encoding="utf-8")
    phases = " ".join(f"{m[0]}={m[1]}s" for m in re.findall(r"^PHASE (\S+) (\S+)$", text, re.M))
    last = ([line for line in text.splitlines() if line.startswith(("SHIP_OK", "SHIP_FAILED", "NOTE"))] or [text[-300:]])
    return name, run.returncode == 0, f"{time.monotonic() - started:.0f}s [{phases}] " + " | ".join(last)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True, help="base release id the robots hold (prepared on this PC)")
    parser.add_argument("--robots", required=True, help="comma list of 9dfk, 8kcn or IPv4 addresses")
    parser.add_argument("--release-id", help="already reserved id (default: reserve the next one)")
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--not-shipped", action="append", default=[])
    parser.add_argument("--full", action="store_true", help="always restart the whole runtime")
    parser.add_argument("--dry-run", action="store_true", help="build and print the plan; no reserve, guard or push")
    args = parser.parse_args(argv)
    started = time.monotonic()
    robots = {name: ROBOTS.get(name, name) for name in args.robots.split(",") if name}
    if not robots or not all(re.fullmatch(r"[0-9.]+|[A-Za-z0-9-]+", ip) for ip in robots.values()):
        parser.error("--robots needs 9dfk, 8kcn or IPv4 addresses")
    if not RELEASE.fullmatch(args.base):
        parser.error("--base must be YYYY.MM.DD-NNN")
    guards = {} if args.dry_run else {name: guard(ip) for name, ip in robots.items()}
    try:
        release_id = args.release_id or (
            next_release_id(datetime.now(timezone.utc).strftime("%Y.%m.%d"), [args.base]) if args.dry_run
            else reserve())
        out_dir = Path("X:/DevTemp") / ("fast-ship-dry" if args.dry_run else "") / f"rosy-release-{release_id}"
        if args.dry_run:
            shutil.rmtree(out_dir, ignore_errors=True)
        build = ["--base-dir", str(Path("X:/DevTemp") / f"rosy-release-{args.base}" / "x" / args.base),
                 "--release-id", release_id, "--revision", args.revision, "--out-dir", str(out_dir)]
        for prefix in args.not_shipped:
            build += ["--not-shipped", prefix]
        if make_delta_release.main(build) != 0:
            raise RuntimeError(f"delta build failed; {release_id} stays reserved (add it to the gaps if unused)")
        tarball = out_dir / f"{release_id}.tar.gz"
        changed = [p.relative_to(out_dir / "x" / release_id).as_posix()
                   for p in (out_dir / "x" / release_id).rglob("*") if p.is_file() and p.name != make_delta_release.MODES_FILE]
        mode, sync = scope(changed)
        if args.full:
            mode = "full"
        holder = re.sub(r"[^A-Za-z0-9._@-]", "_", f"ship-{os.environ.get('USERNAME', 'op')}@{os.environ.get('COMPUTERNAME', 'pc')}")
        stdin = remote_stdin(release_id, args.base, tarball, mode, sync, holder)
        print(f"ship {release_id} on {args.base}: mode={mode} image-layer-sync={int(sync)} "
              f"tarball={tarball.stat().st_size} bytes, built at {time.monotonic() - started:.0f}s")
        if args.dry_run:
            (out_dir / "remote-stdin.sh").write_bytes(stdin)
            for name, ip in robots.items():
                print(f"  {name}: {' '.join(ssh_argv(ip))} < {out_dir / 'remote-stdin.sh'}")
            return 0
        with ThreadPoolExecutor(len(robots)) as pool:
            results = list(pool.map(lambda item: push(item[0], item[1], guards[item[0]], stdin,
                                                      out_dir / f"ship-{item[0]}.txt"), robots.items()))
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        for run in guards.values():
            run.kill()
        print(f"error: {error}", file=sys.stderr)
        return 1
    for name, ok, summary in results:
        print(f"  {name}: {'OK' if ok else 'FAILED'} {summary}")
    print(f"ship {release_id}: {'all OK' if all(r[1] for r in results) else 'FAILED'} in {time.monotonic() - started:.0f}s"
          f" (next: --base {release_id})")
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
