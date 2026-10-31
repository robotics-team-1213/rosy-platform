"""A test's live uvicorn server leaves process logging alone (``log_config=None``).

Without it ``uvicorn.Config`` applies uvicorn's ``LOGGING_CONFIG``, which turns ``propagate`` off on the ``uvicorn``
logger. Under CI's pytest 7.4 ``caplog`` listens only on root, so a later test in the same shard reading a
``uvicorn.error`` record sees nothing (2026-10-31: publish PR 223, after ``test_account_admin_browser``).
The test PCs' pytest 9 still captures it, so only this static check catches a new server there.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = "uvicorn.Config("


def _calls(text: str):
    """Each ``uvicorn.Config(...)`` call's source text, brackets matched."""
    for match in re.finditer(re.escape(CALL), text):
        depth, end = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        yield text[match.start():end]


def test_every_test_uvicorn_config_passes_log_config_none():
    files = subprocess.run(["git", "grep", "-l", CALL, "--", "*test*.py"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.split()
    assert len(files) >= 30, files  # the scan still finds the known live-server tests
    missing = [f"{f}: {call.splitlines()[0]}" for f in files if f != Path(__file__).relative_to(ROOT).as_posix()
               for call in _calls((ROOT / f).read_text(encoding="utf-8")) if "log_config=None" not in call]
    assert missing == [], f"pass log_config=None to a test's uvicorn.Config: {missing}"
