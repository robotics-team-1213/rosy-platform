"""Compatibility import for repository tools; installed runtimes copy the shared implementation."""

import importlib
from pathlib import Path
import sys

_root = str(Path(__file__).resolve().parents[4])
if _root not in sys.path:
    sys.path.insert(0, _root)

# Keep exceptions, monkeypatches and function globals identical for both import paths.
_implementation = importlib.import_module("deploy.hosts.common.release.signing")


def __getattr__(name):
    # spec.loader clients may retain the original module object after execution.
    return getattr(_implementation, name)


sys.modules[__name__] = _implementation
