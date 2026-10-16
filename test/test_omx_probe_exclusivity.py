"""Actual Linux PTY/kernel checks for the temporary native probe open guard."""
import errno
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.geteuid() == 0
                                or not shutil.which("g++") or not shutil.which("fuser"),
                                reason="requires unprivileged Linux, compiler and fuser")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    root = tmp_path_factory.mktemp("exclusive-open")
    guard = root / "guard.so"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-fPIC", "-shared",
                    str(ROOT / "deploy/robot/omx/probe_exclusive_open.cpp"), "-ldl", "-o", str(guard)],
                   check=True, timeout=30)
    source = root / "open.cpp"
    source.write_text('''#include <cstdio>
#include <fcntl.h>
#include <unistd.h>
int main(int argc, char **argv) {
  if (argc != 3) return 3;
  int fd = argv[2][0] == '6' ? open64(argv[1], O_RDWR | O_NOCTTY) : open(argv[1], O_RDWR | O_NOCTTY);
  if (fd < 0) { puts("OPEN_FAILED"); return 2; }
  puts("OPEN_OK"); fflush(stdout); getchar(); close(fd); return 0;
}
''')
    probe = root / "open"
    subprocess.run(["g++", str(source), "-o", str(probe)], check=True, timeout=30)
    return guard, probe


@pytest.fixture
def terminal():
    import pty
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    os.close(slave)
    try:
        yield name
    finally:
        os.close(master)


def environment(guard, path):
    return {**os.environ, "LD_PRELOAD": str(guard), "ROSY_OMX_PROBE_PORT": path}


def test_unprotected_sdk_style_open_allows_another_opener(binaries, terminal):
    """Negative control: the ordinary SDK-style open leaves the race present."""
    _, probe = binaries
    env = {key: value for key, value in os.environ.items() if key != "LD_PRELOAD"}
    child = subprocess.Popen([str(probe), terminal, "open"], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(child.stdout, selectors.EVENT_READ)
            assert ready.select(5)
        assert child.stdout.readline().strip() == "OPEN_OK"
        second = os.open(terminal, os.O_RDWR | os.O_NOCTTY)
        os.close(second)
        child.communicate("\n", timeout=5)
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.kill(); child.communicate()


@pytest.mark.parametrize("symbol", ["open", "64"])
def test_kernel_blocks_another_opener_until_probe_closes(binaries, terminal, symbol):
    guard, probe = binaries
    child = subprocess.Popen([str(probe), terminal, symbol], env=environment(guard, terminal),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(child.stdout, selectors.EVENT_READ)
            assert ready.select(5), "guard did not finish the open check"
        assert child.stdout.readline().strip() == "OPEN_OK"
        with pytest.raises(OSError) as denied:
            os.open(terminal, os.O_RDWR | os.O_NOCTTY)
        assert denied.value.errno == errno.EBUSY
        _, errors = child.communicate("\n", timeout=5)
        assert child.returncode == 0 and "OMX_EXCLUSIVE_OPEN" in errors
    finally:
        if child.poll() is None:
            child.kill(); child.communicate()


def test_racing_existing_owner_is_rejected_and_its_handle_is_preserved(binaries, terminal):
    guard, probe = binaries
    existing = os.open(terminal, os.O_RDWR | os.O_NOCTTY)
    try:
        result = subprocess.run([str(probe), terminal, "open"], env=environment(guard, terminal),
                                input="\n", capture_output=True, text=True, timeout=5)
        assert result.returncode == 2 and "OPEN_FAILED" in result.stdout
        assert "OMX_EXCLUSIVE_OPEN" not in result.stderr
        assert os.fstat(existing)
        reopened = os.open(terminal, os.O_RDWR | os.O_NOCTTY)
        os.close(reopened)
    finally:
        os.close(existing)
