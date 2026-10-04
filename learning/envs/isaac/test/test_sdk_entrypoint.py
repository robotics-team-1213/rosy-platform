"""Kit may leave Python threads alive after close; CLI status must remain truthful."""

import importlib.util
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest


def helper():
    path = Path(__file__).parents[1] / "sdk_entrypoint.py"
    assert path.is_file(), "Bounded SDK entrypoint is missing"
    spec = importlib.util.spec_from_file_location("sdk_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exit_follows_successful_main_cleanup_and_stream_flush(monkeypatch):
    events = []
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(flush=lambda: events.append("stdout")))
    monkeypatch.setattr(sys, "stderr", SimpleNamespace(flush=lambda: events.append("stderr")))
    helper().run_cli(lambda: events.append("main-cleaned"), lambda code: events.append(("exit", code)))
    assert events == ["main-cleaned", "stdout", "stderr", ("exit", 0)]


def test_main_failure_is_printed_and_exits_nonzero_after_cleanup(capsys):
    events = []

    def main():
        try:
            raise RuntimeError("SDK computation failed")
        finally:
            events.append("zero-and-close")

    helper().run_cli(main, lambda code: events.append(("exit", code)))
    assert events == ["zero-and-close", ("exit", 1)]
    assert "RuntimeError: SDK computation failed" in capsys.readouterr().err


@pytest.mark.parametrize("failed", [False, True])
def test_sdk_thread_cannot_hold_process_after_main_finally(failed, tmp_path):
    directory = Path(__file__).parents[1]
    marker = tmp_path / "cleanup.txt"
    script = (
        "import sys, threading\n"
        f"sys.path.insert(0, {str(directory)!r})\n"
        "from sdk_entrypoint import run_cli\n"
        "threading.Thread(target=threading.Event().wait, daemon=False).start()\n"
        "def main():\n"
        "    try:\n"
        f"        {'raise RuntimeError(\"SDK failed\")' if failed else 'pass'}\n"
        "    finally:\n"
        f"        open({str(marker)!r}, 'w').write('zero-and-close')\n"
        "run_cli(main)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=3)
    assert result.returncode == (1 if failed else 0)
    assert marker.read_text() == "zero-and-close"
    if failed:
        assert "RuntimeError: SDK failed" in result.stderr


@pytest.mark.parametrize("failure, expected", [
    (SystemExit("URDF missing"), 1), (SystemExit(2), 2), (SystemExit(0), 0),
    (KeyboardInterrupt(), 130),
])
def test_cli_control_status_is_not_replaced_with_success(failure, expected):
    codes = []

    def main():
        raise failure

    helper().run_cli(main, codes.append)
    assert codes == [expected]


@pytest.mark.parametrize("runner", ["run_rosy", "import_omx"])
def test_public_runner_uses_status_preserving_entrypoint(runner):
    source = (Path(__file__).parents[1] / f"{runner}.py").read_text(encoding="utf-8")
    assert "run_cli(main)" in source

@pytest.mark.parametrize('initial_status', [0, 2])
def test_stream_flush_failure_is_nonzero_and_other_stream_is_flushed(monkeypatch, initial_status):
    events = []
    def broken_flush():
        events.append('stdout')
        raise OSError('Evidence flush failed')
    monkeypatch.setattr(sys, 'stdout', SimpleNamespace(flush=broken_flush))
    monkeypatch.setattr(sys, 'stderr', SimpleNamespace(flush=lambda: events.append('stderr')))
    def main():
        if initial_status:
            raise SystemExit(initial_status)
    helper().run_cli(main, lambda code: events.append(('exit', code)))
    assert events == ['stdout', 'stderr', ('exit', initial_status or 1)]
