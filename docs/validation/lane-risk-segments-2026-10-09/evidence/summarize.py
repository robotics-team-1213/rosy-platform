"""Select review candidates from frozen 10/6 and 10/7 per-frame smoke outputs."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4] / "docs" / "validation"
SOURCES = {
    "1006": ROOT / "drivable-smoke-1006-full-2026-10-08c" / "evidence" / "per_frame.jsonl",
    "1007": ROOT / "drivable-smoke-1007-full-2026-10-08b" / "evidence" / "per_frame.jsonl",
}
HASHES = {
    "1006": "6bca79ca720eb23677b283982a284e9e14ef7b9808aed30362f69da0c6293198",
    "1007": "e99ec8773ea643c347ecf20199556d7dff67ebba90f6086b2236fe3c8b124320",
}


def spans(rows, predicate):
    selected = [row["frame"] for row in rows if predicate(row)]
    runs = []
    for frame in selected:
        if runs and frame == runs[-1][1] + 1:
            runs[-1][1] = frame
        else:
            runs.append([frame, frame])
    return sorted(([a, b, b - a + 1] for a, b in runs), key=lambda r: (-r[2], r[0]))


def summarize():
    result = {}
    for day, path in SOURCES.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == HASHES[day]
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        sessions = {}
        for session in sorted({row["session"] for row in rows}):
            group = [row for row in rows if row["session"] == session]
            assert [row["frame"] for row in group] == list(range(len(group)))
            if day == "1006":
                predicates = {
                    "moving_none_over_half": lambda r: r["moving"] and r["keeper_strategy"] == "none"
                    and r["near_drivable_fraction"] > 0.5,
                    "one_side": lambda r: r["keeper_strategy"] in ("left_only", "right_only"),
                }
            else:
                predicates = {
                    "stop_over_half": lambda r: r["level"] == "STOP" and r["near_drivable_fraction"] > 0.5,
                    "one_boundary": lambda r: r["boundary_tier"] == "ONE",
                }
            sessions[session] = {
                "frames": len(group),
                "candidates": {name: {"count": sum(predicate(row) for row in group),
                                       "longest_spans": spans(group, predicate)[:5]}
                               for name, predicate in predicates.items()},
            }
        result[day] = {"source": path.relative_to(ROOT).as_posix(), "sessions": sessions}
    return result


if __name__ == "__main__":
    assert spans([{"frame": 0}, {"frame": 1}, {"frame": 2}], lambda r: r["frame"] != 1) == [
        [0, 0, 1], [2, 2, 1]]
    print(json.dumps(summarize(), ensure_ascii=False, indent=2))
