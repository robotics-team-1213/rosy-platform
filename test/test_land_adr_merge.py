"""land.merge after the ADR Log's merge=union driver kept two copies of one row (2026-11-04)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import BOM, LOG, commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


def test_the_union_drivers_stale_copy_of_an_adr_row_one_side_edited_is_dropped(repos, capsys):
    """2026-11-04: the Log's union driver kept the branch's edited D-974 row and main's untouched copy (moved by an
    insertion above it) as two rows; lint stopped twice on "duplicate index row"."""
    main, wt = repos
    head = BOM + b"# ROSY ADR Log\r\n\r\n| ID | t | s |\r\n|---|---|---|\r\n"
    commit(main, {".gitattributes": f'"{LOG}" merge=union\n'}, "the repo's union driver")
    subprocess.run(["git", "-C", str(wt), "merge", "-q", "main"], check=True, capture_output=True)
    commit(wt, {LOG: head + b"| D-1 | t1 | Accepted, Harbor done |\r\n| D-2 | t2 | Accepted |\r\n"}, "edit D-1")
    commit(main, {LOG: head + b"| D-3 | t3 | Accepted |\r\n| D-1 | t1 | Accepted |\r\n| D-2 | t2 | Accepted |\r\n"},
           "a peer adds D-3 right above D-1")
    land.merge(wt, git(main, "rev-parse", "HEAD"), "feat/x", sys.executable, False)
    data = (wt / LOG).read_bytes()
    assert data.count(b"| D-1 |") == 1 and b"Harbor done" in data and b"| D-3 |" in data
    assert "dropped the merge base's row of ['D-1']" in capsys.readouterr().out
