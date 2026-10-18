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
    return {**os.environ, "LD_PRELOAD": str(guard), "ROSY_OMX_PROBE_PORT": path,
            "ROSY_OMX_PROBE_DEVICE_ID": str(os.stat(path).st_rdev)}


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


def test_changed_device_identity_is_rejected_before_traffic(binaries, terminal):
    guard, probe = binaries
    env = environment(guard, terminal)
    env["ROSY_OMX_PROBE_DEVICE_ID"] = str(os.stat(terminal).st_rdev + 1)
    result = subprocess.run([str(probe), terminal, "open"], env=env,
                            input="\n", capture_output=True, text=True, timeout=5)
    assert result.returncode == 2 and "OPEN_FAILED" in result.stdout
    assert "OMX_EXCLUSIVE_OPEN" not in result.stderr


def test_worker_open_during_library_constructor_does_not_wait_for_loader(binaries, tmp_path):
    """ROS tracing libraries can open ordinary files from a constructor's worker."""
    guard, _ = binaries
    source = tmp_path / "constructor.cpp"
    source.write_text('''#include <thread>
#include <fcntl.h>
#include <unistd.h>
#include <cstdlib>
__attribute__((constructor)) static void initialize() {
  std::thread worker([] { int fd = open("/dev/null", O_RDONLY);
                         if (fd < 0) _exit(7); close(fd); });
  worker.join();
}
''')
    library = tmp_path / "constructor.so"
    subprocess.run(["g++", "-shared", "-fPIC", "-pthread", str(source), "-o", str(library)],
                   check=True, timeout=30)
    loader = tmp_path / "loader.cpp"
    loader.write_text('''#include <dlfcn.h>
int main(int argc, char **argv) { return argc != 2 || !dlopen(argv[1], RTLD_NOW); }
''')
    executable = tmp_path / "loader"
    subprocess.run(["g++", str(loader), "-ldl", "-o", str(executable)], check=True, timeout=30)
    result = subprocess.run([str(executable), str(library)],
                            env={**os.environ, "LD_PRELOAD": str(guard)},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
