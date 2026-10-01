"""Turn a GitHub-built unsigned native payload into a signed tarball ready for rosy-release-push.ps1.

One command for the hand steps between "the runner built the payload" and the push
(skill rosy-release-push, steps 3-5):

    python tools/release/prepare_payload_release.py --run 36865620181 --robot 192.168.1.202
    python tools/release/prepare_payload_release.py --artifact-dir X:/DevTemp/a --release-id 2026.10.01-021 --skip-abi

1. download: the run's `rosy-native-payload-unsigned-<id>-<sha>` artifact through
   download_artifact.py (parallel ranges, CRC check), then `<id>.unsigned.tar.gz` from it.
   The artifact folder drops dotfiles (install/.colcon_install_layout), so it is never signed.
2. lists: `required-ros-packages.txt` must name only ROSY packages in `rosy-packages.txt`.
3. ABI: read-only `dpkg-query -W -f=<status, name, version> 'ros-jazzy-*'` over ssh on each
   --robot. Every package installed (status `ii`) on both sides must have the same version;
   `rc` and other states, and an empty version, are "not installed". Comparing zero
   packages is a failure, not a pass.
4. extract: into a temp dir beside `<out>/x/<id>`, renamed into place; an existing
   `<out>/x/<id>` is refused, never reused.
5. sign (sign_image_release.py) and pack (build_payload_release.py pack --modes-from).
6. print the rosy-release-push.ps1 lines (dry run first). Nothing is pushed.

Standard library only. Needs Python 3.12+ (tarfile filter='tar').
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Callable
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
ARTIFACT_PREFIX = "rosy-native-payload-unsigned-"
ARTIFACT_NAME = re.compile(r"rosy-native-payload-unsigned-(\d{4}\.\d{2}\.\d{2}-\d{3})-([0-9a-f]{40})")
RELEASE_ID = re.compile(r"\d{4}\.\d{2}\.\d{2}-\d{3}")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")
# Single quotes only: the remote shell passes ${...}, \t and \n to dpkg-query unexpanded.
# The status column lets "rc" (removed, config files left) packages, which still report
# their old version, be dropped.
DPKG_COMMAND = "dpkg-query -W -f='${db:Status-Abbrev}\\t${binary:Package}\\t${Version}\\n' 'ros-jazzy-*'"
PUSH_SCRIPT = r"deploy\robot\pinky_pro\rosy-release-push.ps1"

SshRunner = Callable[[list[str]], tuple[int, str, str]]
ToolRunner = Callable[[list[str]], int]


class PrepareError(RuntimeError):
    pass


# --- lists -----------------------------------------------------------------

def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def parse_release_ros_packages(text: str) -> dict[str, str]:
    """The release's ros-packages.txt: one `name=version` per line."""
    packages: dict[str, str] = {}
    for line in _lines(text):
        name, sep, version = line.partition("=")
        if not sep or not name.strip() or not version.strip():
            raise PrepareError(f"ros-packages.txt line is not name=version: {line!r}")
        packages[name.strip()] = version.strip()
    return packages


def parse_dpkg_query(text: str) -> dict[str, str]:
    """DPKG_COMMAND output: `status<TAB>name<TAB>version`.

    Only status `ii` (installed) counts; an empty version also means not installed.
    """
    packages: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise PrepareError(f"dpkg-query line is not status<TAB>name<TAB>version: {line!r}")
        status, name, version = fields
        name, version = name.strip().split(":", 1)[0], version.strip()
        if status.startswith("ii") and name and version:
            packages[name] = version
    return packages


class AbiResult:
    # Plain class, not @dataclass: the tests load this file by path without a sys.modules entry.
    def __init__(self, compared: int, release_only: int, mismatches: list[tuple[str, str, str]]):
        self.compared = compared
        self.release_only = release_only
        self.mismatches = mismatches

    @property
    def ok(self) -> bool:
        return self.compared > 0 and not self.mismatches


def compare_abi(release: dict[str, str], robot: dict[str, str]) -> AbiResult:
    shared = sorted(set(release) & set(robot))
    return AbiResult(
        compared=len(shared),
        release_only=len(set(release) - set(robot)),
        mismatches=[(name, release[name], robot[name]) for name in shared if release[name] != robot[name]],
    )


def missing_required(required_text: str, inventory_text: str) -> list[str]:
    """Required ROSY packages (required-ros-packages.txt) absent from rosy-packages.txt."""
    inventory = set(_lines(inventory_text))
    return [name for name in _lines(required_text) if name not in inventory]


# --- ssh -------------------------------------------------------------------

def ssh_argv(host: str, local_appdata: Path) -> list[str]:
    rosy = Path(local_appdata) / "Rosy"
    return ["ssh", "-i", str(rosy / "ssh" / "rosy-operator-ed25519"),
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f'UserKnownHostsFile="{rosy / "known_hosts"}"', "-o", "ConnectTimeout=5",
            f"rosy@{host}", DPKG_COMMAND]


def run_ssh(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 255, "", f"{type(error).__name__}: {error}"
    return (done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"))


def check_robot_abi(host: str, release: dict[str, str], ssh_runner: SshRunner,
                    *, local_appdata: Path) -> tuple[bool, str]:
    code, out, err = ssh_runner(ssh_argv(host, local_appdata))
    if code != 0:
        detail = (err.strip().splitlines() or ["no output"])[-1]
        return False, f"{host}: ABI CHECK FAILED - ssh/dpkg-query exit {code}: {detail}"
    result = compare_abi(release, parse_dpkg_query(out))
    if result.mismatches:
        shown = "; ".join(f"{name} release {ours} robot {theirs}" for name, ours, theirs in result.mismatches[:5])
        more = f" (+{len(result.mismatches) - 5} more)" if len(result.mismatches) > 5 else ""
        return False, f"{host}: ABI MISMATCH in {len(result.mismatches)} of {result.compared}: {shown}{more}"
    if not result.ok:
        return False, f"{host}: ABI CHECK FAILED - compared 0 packages (robot listed none of the release's)"
    return True, (f"{host}: ABI OK - {result.compared} shared ros-jazzy packages match "
                  f"({result.release_only} release-only, not on the robot)")


# --- tarball ---------------------------------------------------------------

def _member_name(name: str) -> str:
    return str(PurePosixPath(name)).removeprefix("./")


def read_lists(tarball: Path) -> dict[str, str]:
    wanted = {"ros-packages.txt", "rosy-packages.txt", "required-ros-packages.txt"}
    found: dict[str, str] = {}
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            name = _member_name(member.name)
            if name in wanted and member.isreg():
                found[name] = tar.extractfile(member).read().decode("utf-8")
    missing = sorted(wanted - set(found))
    if missing:
        raise PrepareError(f"{tarball.name} has no {', '.join(missing)} at its top level")
    return found


def _remove_tree(path: Path) -> None:
    def make_writable(function, target, _error):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    shutil.rmtree(path, onexc=make_writable)


def refuse_existing(release_dir: Path) -> None:
    if release_dir.exists():
        raise PrepareError(f"{release_dir} already exists; it may be a partial extract. "
                           "Remove it or use a new --out-dir")


def extract_release(tarball: Path, target: Path) -> Path:
    """Extract into a temp dir beside `target`, check it, then rename it into place."""
    target = Path(target)
    refuse_existing(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.partial-", dir=target.parent))
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    kind = "symlink" if member.issym() else "hardlink"
                    raise PrepareError(f"{tarball.name} has a {kind} member {member.name!r}; refusing to extract")
            tar.extractall(temporary, filter="tar")
        manifest = temporary / "manifest.json"
        if not manifest.is_file():
            raise PrepareError(f"{tarball.name} has no top-level manifest.json")
        release_id = json.loads(manifest.read_text(encoding="utf-8")).get("release_id")
        if release_id != target.name:
            raise PrepareError(f"manifest.json release_id is {release_id!r}, not {target.name}")
        os.rename(temporary, target)
    except BaseException:
        _remove_tree(temporary)
        raise
    return target


# --- artifact --------------------------------------------------------------

def pick_artifact(names: list[str], release_id: str | None) -> tuple[str, str]:
    matches = [(name, m.group(1)) for name in names if (m := ARTIFACT_NAME.fullmatch(name))]
    if release_id is not None:
        matches = [item for item in matches if item[1] == release_id]
    if len(matches) != 1:
        wanted = f"{ARTIFACT_PREFIX}{release_id or '<id>'}-<sha>"
        raise PrepareError(f"expected one artifact named {wanted}, found {len(matches)} in {sorted(names)}")
    return matches[0]


def _download_tool():
    spec = importlib.util.spec_from_file_location("download_artifact", Path(__file__).with_name("download_artifact.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def download_unsigned(run: int, release_id: str | None, out_dir: Path | None, repo: str | None,
                      workers: int) -> tuple[str, Path]:
    """Download the run's unsigned artifact; returns (release id, <out>/<id>.unsigned.tar.gz)."""
    da = _download_tool()
    try:
        github = da.GitHub("https://api.github.com", repo or da.default_repo(), da.github_token())
        listed = github._json(f"/runs/{run}/artifacts?per_page=100")
        name, release_id = pick_artifact([item.get("name", "") for item in listed.get("artifacts", [])], release_id)
        out_dir = out_dir or default_out_dir(release_id)
        refuse_existing(out_dir / "x" / release_id)
        artifact = github.artifact(None, run, name)
        archive = out_dir / f"{name}.zip"
        if archive.exists():
            da.check_archive(archive, int(artifact["size_in_bytes"]))
            print(f"already downloaded (size and zip CRC checked): {archive}", flush=True)
        else:
            da.Downloader(github, artifact, archive, workers, 10.0).run()
    except da.DownloadError as error:
        raise PrepareError(str(error)) from None
    member = f"{release_id}.unsigned.tar.gz"
    tarball = out_dir / member
    partial = out_dir / f".{member}.partial"
    with zipfile.ZipFile(archive) as bundle, bundle.open(member) as source, partial.open("wb") as output:
        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    os.replace(partial, tarball)
    return release_id, tarball


def default_out_dir(release_id: str) -> Path:
    return Path("X:/DevTemp") / f"rosy-release-{release_id}"


# --- sign, pack, print -----------------------------------------------------

def run_tool(argv: list[str]) -> int:
    return subprocess.run(argv, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}).returncode


def _ps_path(path: Path) -> str:
    """A PowerShell single-quoted literal: nothing expands, ' is written ''."""
    return "'" + str(path).replace("'", "''") + "'"


def push_commands(hosts: list[str], tarball: Path) -> list[str]:
    lines = []
    for host in hosts or ["<robot-ip>"]:
        base = f"{PUSH_SCRIPT} -Robot {host} -Tarball {_ps_path(tarball)}"
        lines += [f"{base} -PrintCommands   # dry run", base]
    return lines


def _phase(timings: dict[str, float], name: str, started: float) -> None:
    timings[name] = time.monotonic() - started
    print(f"[{name}] {timings[name]:.1f}s", flush=True)


def main(argv: list[str] | None = None, *, ssh_runner: SshRunner = run_ssh,
         tool_runner: ToolRunner = run_tool) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=int, help="workflow run id of build-native-payload.yml")
    source.add_argument("--artifact-dir", type=Path, help="an already downloaded artifact folder (skips the download)")
    parser.add_argument("--release-id", help="YYYY.MM.DD-NNN (default: from the artifact name or folder)")
    parser.add_argument("--out-dir", type=Path, help=r"work folder (default X:\DevTemp\rosy-release-<id>)")
    parser.add_argument("--robot", action="append", default=[], help="robot host for the ABI check (repeatable)")
    parser.add_argument("--key-name", default="rosy-release-2026-01")
    parser.add_argument("--skip-abi", action="store_true", help="skip the robot ROS ABI check")
    parser.add_argument("--repo", help="OWNER/NAME (default: this checkout's origin)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    if not args.robot and not args.skip_abi:
        parser.error("pass --robot <ip> (repeatable) or --skip-abi")
    for host in args.robot:
        if not HOST.fullmatch(host):
            parser.error(f"--robot {host!r} is not a host name or address")
    if args.release_id is not None and not RELEASE_ID.fullmatch(args.release_id):
        parser.error("--release-id must be YYYY.MM.DD-NNN")

    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    private_key = local_appdata / "Rosy" / "signing" / f"{args.key_name}.private.pem"
    public_key = RELEASE_TOOLS / "public-keys" / f"{args.key_name}.pem"
    timings: dict[str, float] = {}
    try:
        for key in (private_key, public_key):
            if not key.is_file():
                raise PrepareError(f"signing key not found: {key}")

        started = time.monotonic()
        if args.run is not None:
            if args.release_id is not None:
                refuse_existing((args.out_dir or default_out_dir(args.release_id)) / "x" / args.release_id)
            release_id, unsigned = download_unsigned(args.run, args.release_id, args.out_dir, args.repo, args.workers)
            out_dir = args.out_dir or default_out_dir(release_id)
        else:
            candidates = sorted(args.artifact_dir.glob(f"{args.release_id or '*'}.unsigned.tar.gz"))
            if len(candidates) != 1:
                raise PrepareError(f"expected one <id>.unsigned.tar.gz in {args.artifact_dir}, found {len(candidates)}")
            unsigned = candidates[0]
            release_id = unsigned.name.removesuffix(".unsigned.tar.gz")
            if not RELEASE_ID.fullmatch(release_id):
                raise PrepareError(f"{unsigned.name} is not <YYYY.MM.DD-NNN>.unsigned.tar.gz")
            out_dir = args.out_dir or default_out_dir(release_id)
        release_dir = out_dir / "x" / release_id
        signed = out_dir / f"{release_id}.tar.gz"
        _phase(timings, "download", started)
        refuse_existing(release_dir)

        started = time.monotonic()
        lists = read_lists(unsigned)
        missing = missing_required(lists["required-ros-packages.txt"], lists["rosy-packages.txt"])
        if missing:
            raise PrepareError(f"required-ros-packages.txt names packages missing from rosy-packages.txt: {missing}")
        release_ros = parse_release_ros_packages(lists["ros-packages.txt"])
        print(f"release {release_id}: {len(release_ros)} ros-jazzy packages, required ROSY packages all present")
        if args.skip_abi:
            print("ABI check skipped (--skip-abi)")
        else:
            verdicts = [check_robot_abi(host, release_ros, ssh_runner, local_appdata=local_appdata)
                        for host in args.robot]
            for _ok, line in verdicts:
                print(line, flush=True)
            if not all(ok for ok, _line in verdicts):
                raise PrepareError("ROS ABI check failed; do not push this payload to that robot")
        _phase(timings, "abi", started)

        started = time.monotonic()
        extract_release(unsigned, release_dir)
        _phase(timings, "extract", started)

        started = time.monotonic()
        if tool_runner([sys.executable, str(RELEASE_TOOLS / "sign_image_release.py"), str(release_dir),
                        "--private-key", str(private_key), "--public-key", str(public_key)]) != 0:
            raise PrepareError(f"sign_image_release.py failed; delete {release_dir} before rerunning")
        _phase(timings, "sign", started)

        started = time.monotonic()
        if tool_runner([sys.executable, str(RELEASE_TOOLS / "build_payload_release.py"), "pack",
                        "--release-dir", str(release_dir), "--out", str(signed),
                        "--modes-from", str(unsigned), "--public-key", str(public_key)]) != 0:
            raise PrepareError(f"build_payload_release.py pack failed; delete {release_dir} before rerunning")
        _phase(timings, "pack", started)
    # ValueError covers json.JSONDecodeError and UnicodeDecodeError; EOFError is a truncated gzip.
    except (PrepareError, OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"\nsigned payload: {signed}")
    print("timings: " + ", ".join(f"{name} {seconds:.1f}s" for name, seconds in timings.items()))
    print("\nNot pushed. From the repo root, dry run first:")
    for line in push_commands(args.robot, signed):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
