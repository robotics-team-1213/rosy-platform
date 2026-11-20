"""CORE + Fleet integration tests: CORE's gateway app driven by real Fleet server code.

They moved out of middleware/core/gateway/test (2026-11-19 app independence) so the
pinky-owned gateway suite imports no Fleet code. They still use the gateway suite's
fixtures and helper modules, so that directory and its conftest's import paths come in here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

GATEWAY_TEST = Path(__file__).resolve().parents[3] / "middleware" / "core" / "gateway" / "test"
if str(GATEWAY_TEST) not in sys.path:
    sys.path.insert(0, str(GATEWAY_TEST))

# Loaded under its own name: both files are `conftest`, and executing it adds the gateway import paths.
_spec = importlib.util.spec_from_file_location("gateway_test_conftest", GATEWAY_TEST / "conftest.py")
_gateway = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gateway)
core_client = _gateway.core_client
