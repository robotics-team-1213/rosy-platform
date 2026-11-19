"""Retry labels follow a physical attempt across audited library changes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_decisions as decisions  # noqa: E402


def _attempt(n: int, result: str) -> dict:
    return {"attempt_id": f"trial-{n:03d}", "outcome": "placed" if result == "placed" else "failed",
            "transfer": {"result": result, "steps": []}, "fail_class": result}


def test_retry_skips_only_reviewed_library_rotation():
    retry = {"decision_id": "retry-1", "attempt_id": "trial-001", "stage": "retry", "by": "measurement"}
    first = _attempt(1, "empty")
    placed = _attempt(4, "placed")
    rotation = _attempt(2, "replanned")

    joined = decisions.join([retry], [first, rotation, _attempt(3, "replanned"), placed])[0]
    assert (joined["outcome"], joined["label"]) == ("placed", "validated_by_outcome")
    assert (decisions.join([retry], [first, _attempt(2, "placed")])[0]["outcome"] == "placed")
    assert (decisions.join([retry], [first, _attempt(2, "load_refused"), placed])[0]["label"]
            == "unvalidated")
