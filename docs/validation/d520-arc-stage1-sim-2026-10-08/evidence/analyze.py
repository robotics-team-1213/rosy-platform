"""Recompute D-520 stage 1 radial errors from recorded Gazebo ground truth."""

import json
import math
from pathlib import Path


ROOT = Path(__file__).parent
CENTER = (-0.3357, 0.0011)
RADIUS = 0.2514


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def measure(trace, seq):
    arc = [row for row in trace if row.get("gt") and row.get("arc", {}).get("arc_seq") == seq
           and row["arc"]["state"] in ("running", "ended", "stopped")]
    if not arc:
        return None
    dr = [math.hypot(row["gt"][0] - CENTER[0], row["gt"][1] - CENTER[1]) - RADIUS
          for row in arc]
    x, y, yaw = arc[0]["gt"]
    tangent = math.atan2(y - CENTER[1], x - CENTER[0]) + math.pi / 2
    heading = math.degrees(math.atan2(math.sin(yaw - tangent), math.cos(yaw - tangent)))
    return {"start_dr_m": dr[0], "end_dr_m": dr[-1], "flow_m": dr[-1] - dr[0],
            "max_abs_dr_m": max(map(abs, dr)), "entry_heading_err_deg": heading,
            "arc_samples": len(arc),
            "final_arc": arc[-1]["arc"]}


def main():
    result = {}
    for case, folder in (("SW", "sw3"), ("NE", "ne3")):
        recorded = json.loads((ROOT / folder / "summary.json").read_text())["results"]
        result[case] = []
        for index, run in enumerate(recorded):
            # The API retains the previous arc. A rejected entry has no current arc to measure.
            metric = (measure(rows(ROOT / folder / f"{case}_{index}_arc.jsonl"),
                              run["arc"]["arc_seq"]) if run["result"] in ("ended", "stopped")
                      else None)
            result[case].append({"index": index, "entry": run["result"],
                                 "reason": run.get("final_reason"), "metric": metric})
    chain = rows(ROOT / "chain2" / "arc.jsonl")
    result["chain"] = {"SW_to_SE": measure(chain, 1), "SE_to_NE": measure(chain, 2)}
    for case, folder in (("SW", "sw_gain11"), ("NE", "ne_gain11")):
        run = json.loads((ROOT / folder / "summary.json").read_text())["results"][0]
        result[f"{case}_gain11"] = measure(rows(ROOT / folder / f"{case}_0_arc.jsonl"),
                                           run["arc"]["arc_seq"])
    assert len(result["SW"]) == len(result["NE"]) == 3
    assert all(run["metric"] for run in result["SW"])
    assert sum(run["metric"] is not None for run in result["NE"]) == 2
    assert result["chain"]["SE_to_NE"]
    assert result["SW_gain11"] and result["NE_gain11"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
