"""D-520 read-only replay metrics; no motion decision or accepted labels."""

import importlib.util
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "docs/validation/lane-arc-fit-candidate-2026-10-09"
          / "evidence/fit_first.py")
spec = importlib.util.spec_from_file_location("arc_entry_replay", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_candidate_flicker_and_consecutive_miss_include_edge_gaps():
    summary = module.summarize_hits([False, False, True, False, True, False, False])
    assert summary == {"frames": 7, "candidate_frames": 2, "transitions": 4,
                       "longest_consecutive_miss": 2, "first_candidate_index": 2}


def test_no_candidate_is_not_a_success():
    summary = module.summarize_hits([False] * 3)
    assert summary["candidate_frames"] == 0
    assert summary["longest_consecutive_miss"] == 3
    assert summary["first_candidate_index"] is None
