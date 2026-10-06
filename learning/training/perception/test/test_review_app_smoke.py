"""tools/review_app_smoke.py serves a state, screenshots every screen and reports clean."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_review_app import open_store

pytestmark = pytest.mark.skipif(os.getenv('ROSY_RUN_BROWSER_TESTS') != '1',
                                reason='requires explicit local Chromium browser run')
TOOL = Path(__file__).resolve().parents[4] / 'tools/review_app_smoke.py'


def test_smoke_tool_passes_on_fixture_state(tmp_path):
    pytest.importorskip('playwright.sync_api')
    store = open_store(tmp_path)
    out = tmp_path / 'shots'
    result = subprocess.run([sys.executable, str(TOOL), '--state', str(store.state), '--out', str(out)],
                            capture_output=True, text=True, encoding='utf-8', timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"frames": 2' in result.stdout
    assert len(list(out.glob('*.png'))) == 10


def test_smoke_tool_refuses_a_folder_without_state(tmp_path):
    result = subprocess.run([sys.executable, str(TOOL), '--state', str(tmp_path)],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode != 0 and 'reviews.sqlite3' in result.stderr
