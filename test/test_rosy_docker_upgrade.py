"""Tests for deploy/site/host-state/rosy-docker-upgrade Ubuntu package handling."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/site/host-state/rosy-docker-upgrade"
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX /bin/bash and stub tools required")


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _run_with_stubs(tmp_path: Path, installed: dict[str, str], candidates: dict[str, str]):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"

    _write_exec(bindir / "flock", "exit 0\n")
    _write_exec(bindir / "docker", "echo 'docker server 29.1.3'\n")
    _write_exec(
        bindir / "dpkg-query",
        f"""
fmt=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -W) shift ;;
    -f) fmt="$2"; shift 2 ;;
    *) break ;;
  esac
done
rc=0
for pkg in "$@"; do
  ver=""
  case "$pkg" in
{chr(10).join(f'    {k}) ver="{v}" ;;' for k, v in installed.items())}
  esac
  if [ -z "$ver" ]; then
    echo "dpkg-query: no packages found matching $pkg" >&2
    rc=1
    continue
  fi
  case "$fmt" in
    *'db:Status-Status'*) printf 'installed\\n' ;;
    *'db:Status-Abbrev'*) printf '%s ii %s\\n' "$pkg" "$ver" ;;
    *'${{Version}}'*) printf '%s\\n' "$ver" ;;
  esac
done
exit "$rc"
""",
    )
    _write_exec(
        bindir / "dpkg",
        f"""
if [ "${{1:-}}" = "--compare-versions" ]; then
  python3 -c 'import sys; sys.exit(0 if tuple(map(int, sys.argv[1].split("."))) > tuple(map(int, sys.argv[2].split("."))) else 1)' "$2" "$4"
  exit $?
fi
echo "dpkg $*" >> "{log}"
""",
    )
    _write_exec(
        bindir / "apt-cache",
        f"""
if [ "${{1:-}}" = "policy" ]; then
  cand="(none)"
  case "$2" in
{chr(10).join(f'    {k}) cand="{v}" ;;' for k, v in candidates.items())}
  esac
  echo "$2:"
  echo "  Candidate: $cand"
fi
""",
    )
    _write_exec(
        bindir / "apt-get",
        f"""
echo "apt-get $*" >> "{log}"
if [ "${{1:-}}" = "download" ]; then
  shift
  for p in "$@"; do
    : > "${{p}}.deb"
  done
fi
""",
    )

    env = {
        **os.environ,
        "PATH": f"{bindir}:/usr/bin:/bin",
        "ROSY_HOST_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "ROSY_DOCKER_DEBS_DIR": str(tmp_path / "debs"),
    }
    res = subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    return res, calls


def test_rosy_docker_upgrade_syntax():
    res = subprocess.run(["/bin/bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, res.stderr


def test_ubuntu_docker_io_skips_uninstalled_ce_plugins(tmp_path: Path):
    versions = {"runc": "1.3.4", "containerd": "2.2.1", "docker.io": "29.1.3", "docker-compose-v2": "2.40.3"}
    res, calls = _run_with_stubs(tmp_path, versions, versions)
    assert res.returncode == 0, res.stderr
    assert "rosy-docker-upgrade: already current" in res.stdout
    assert "apt-get download" not in calls
    assert "dpkg -i" not in calls


def test_ubuntu_docker_io_upgrades_only_installed_outdated_packages(tmp_path: Path):
    installed = {"runc": "1.3.4", "containerd": "2.2.1", "docker.io": "29.1.3", "docker-compose-v2": "2.40.3"}
    candidates = {**installed, "docker-compose-v2": "2.40.4"}
    res, calls = _run_with_stubs(tmp_path, installed, candidates)
    assert res.returncode == 0, res.stderr
    assert "rosy-docker-upgrade: docker-compose-v2 2.40.3 -> 2.40.4" in res.stdout
    assert "apt-get download docker-compose-v2" in calls
    assert "docker-buildx-plugin" not in calls
    assert "docker-compose-plugin" not in calls
