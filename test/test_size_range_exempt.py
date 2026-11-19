"""11-19: the D-766 per-commit size rule skips only exact shas listed in tools/harness/size_range_exempt.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import size_range  # noqa: E402


def test_only_listed_shas_skip_the_per_commit_rule(tmp_path, monkeypatch):
    def git(*args):
        if args[0] == "rev-list" and "--parents" in args:
            return f"{args[-1]} p1 p2"  # merges: the CRLF and metrics rules skip them
        if args[0] == "rev-list":
            return "aaa\nbbb"
        return args[-1]
    monkeypatch.setattr(size_range, "_git", git)
    monkeypatch.setattr(size_range, "check", lambda commit: ["x.py: 601 lines is over 600"])
    exempt = tmp_path / "size_range_exempt.json"
    monkeypatch.setattr(size_range, "EXEMPT_FILE", exempt)
    assert size_range.main(["base", "head"]) == 1
    exempt.write_text(json.dumps([{"commit": "aaa", "reason": "r"}]), encoding="utf-8")
    assert size_range.main(["base", "head"]) == 1  # bbb is still red
    exempt.write_text(json.dumps([{"commit": "aaa", "reason": "r"}, {"commit": "bbb", "reason": "r"}]), encoding="utf-8")
    assert size_range.main(["base", "head"]) == 0
