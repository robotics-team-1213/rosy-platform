"""Source paths for the cross-domain camera SIM when collected alone."""
from pathlib import Path

import pytest


@pytest.fixture
def pipeline_sources(monkeypatch):
    root = Path(__file__).resolve().parents[4]
    for relative in ('operations/fleet', 'operations/fleet/test', 'operations/world/src',
                     'operations/decision/src', 'operations/site_execution/src', 'operations/overhead',
                     'operations/apps/games', 'operations/situation',
                     'middleware/core/services/test'):
        monkeypatch.syspath_prepend(str(root / relative))
