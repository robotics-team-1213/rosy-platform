"""Report only: test modules that add sys.path entries while pytest collects them.

Such a module lets later modules in the same process import what they cannot alone (2026-10-26,
learning/training/omx/test/test_native_cycle.py; tools/land_isolation.py's gate catches the failure itself).
The summary names each inserter so the path can move into a conftest or go. It never fails a run, and it skips
the folder pytest itself inserts (prepend import mode). Under xdist each worker also gets its own HOME, XDG dirs and TMPDIR (isolate_worker). Under xdist the workers hand their findings to the
controller. Loaded when the repository root is the rootdir (remote_pytest.py's ``--rootdir=.``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect
except ImportError:
    pass
else:
    # 5 s default: 11-07 FULLs lost hours to UI waits missing it under load, each passing alone. A real failure still fails.
    expect.set_options(timeout=15_000)

def isolate_worker(env, base: str) -> None:
    """Give an xdist worker its own HOME, XDG dirs and TMPDIR so tests that write there cannot meet another worker's files."""
    worker = env.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    root = Path(base) / f"rosy-{worker}-{os.getpid()}"
    for key, sub in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp")):
        (root / sub).mkdir(parents=True, exist_ok=True)
        env[key] = str(root / sub)


def pytest_configure(config):
    import tempfile
    isolate_worker(os.environ, tempfile.gettempdir())


_ADDED: dict[str, list[str]] = {}
KEY = "rosy_syspath_added"


def _own_dir(path: Path) -> str:
    """The folder prepend import mode puts on sys.path for this module: the first one up without __init__.py."""
    folder = path.parent
    while (folder / "__init__.py").is_file():
        folder = folder.parent
    return str(folder)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    before = set(sys.path) if isinstance(collector, pytest.Module) else None
    yield
    if before is not None:
        own = _own_dir(Path(collector.path))
        if added := list(dict.fromkeys(p for p in sys.path if p not in before and p != own)):
            root = str(collector.config.rootpath)
            _ADDED[collector.nodeid] = [os.path.relpath(p, root) if p.startswith(root) else p for p in added]


def pytest_sessionfinish(session):
    if hasattr(session.config, "workeroutput"):  # an xdist worker: the controller prints
        session.config.workeroutput[KEY] = dict(_ADDED)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    _ADDED.update(getattr(node, "workeroutput", {}).get(KEY, {}))


def pytest_terminal_summary(terminalreporter):
    if _ADDED:
        terminalreporter.write_sep("-", f"sys.path added by {len(_ADDED)} test module(s) at collection (report only)")
        for nodeid, paths in sorted(_ADDED.items()):
            terminalreporter.write_line(f"{nodeid}: {', '.join(paths)}")
