"""Compatibility import for the shared operator/verification tools guest."""
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules[__name__] = importlib.import_module('tools.release.os_tools_vm')
