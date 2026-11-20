"""Shared fixtures of the station camera pipeline SIM.

The Fleet-calling pipeline test itself lives in
test/integration/core_fleet/test_station_camera_http_pipeline.py (CORE + Fleet integration).
"""
import asyncio
from pathlib import Path

import pytest

from test_station_docking_api import station_api  # noqa: F401


SIM_WAIT_S = 30.


async def _sim_call(function, *args, **kwargs):
    # SIM time controls permits; host ASGI/journal scheduling gets its own bounded test budget.
    return await asyncio.wait_for(function(*args, **kwargs), timeout=SIM_WAIT_S)


@pytest.fixture
def pipeline_sources(monkeypatch):
    """This cross-domain test must also run alone, without sibling conftest collection."""
    import cv2

    root = Path(__file__).resolve().parents[4]
    for relative in ('operations/fleet', 'operations/fleet/test', 'operations/world/src',
                     'operations/decision/src', 'operations/site_execution/src', 'operations/overhead',
                     'operations/apps/games', 'operations/situation',
                     'middleware/core/services/test'):
        monkeypatch.syspath_prepend(str(root / relative))
    # SIM durability is not under test: fsync on every ledger commit dominated wall time (CPU ~1/3 of wall).
    import sqlite3
    real_connect = sqlite3.connect

    class _NoSyncConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if str(sql).strip().lower().startswith('pragma synchronous'):
                sql = 'PRAGMA synchronous=OFF'
            return super().execute(sql, *args)

    def connect(*args, **kwargs):
        connection = real_connect(*args, **{**kwargs, 'factory': _NoSyncConnection})
        connection.execute('PRAGMA synchronous=OFF')
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    previous_threads = cv2.getNumThreads()
    cv2.setNumThreads(1)  # Small SIM images must not consume the host's entire OpenCV pool.
    try:
        yield
    finally:
        cv2.setNumThreads(previous_threads)

