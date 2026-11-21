#!/usr/bin/env python3
"""Write the belt -> ship hold task cards (rosy.omx-task-card.v1) for every hold h1/h2 x row r0-r2 x layer l0-l2 spot.

The bench lists cards from <prep>/tasks/*.yaml on the cell PC; the repository keeps no card originals, so this is the one source.
Usage: ship_task_cards.py --out DIR [--root-prefix /home/<user>/rosy-data/omx-leader]   (existing files are overwritten; copy with cp -n)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

HOLDS, ROWS, LAYERS = (1, 2), (0, 1, 2), (0, 1, 2)
ROW_NAME = ("A side row", "middle row", "B side row")  # r0 is nearest arm_a, r2 arm_b (tools/sim/omx_two_arm_sites.py r08_sites)
LAYER_NAME = ("tier 1 (floor)", "tier 2", "tier 3 (top)")  # screen counts tiers from 1, IDs from l0
H1_ARM = {0: "arm_a", 1: "arm_b", 2: "arm_b"}  # tools/sim/omx_two_arm_sites.py R08_STACK; hold 2 has no arm in any source
UNVERIFIED = "도달 미검증(planned_unverified): shared/web/cell-site-map.json lists arm_a and arm_b for every spot, none verified on the real arm"


def card(hold: int, row: int, layer: int, root_prefix: str) -> dict:
    spot = f"ship-h{hold}r{row}-l{layer}"
    task_id = f"belt-to-{spot}"
    limits = [UNVERIFIED]
    layout = {"origin": "belt", "target_slot": spot}
    if hold == 1:
        layout["shot_arm"] = H1_ARM[row]
        limits.append("sim only: hold 1 is the one in reach (deploy/robot/omx/sim/two_arm_tasks.json)")
    else:
        limits.append("sim: hold 2 is not in reach (deploy/robot/omx/sim/two_arm_tasks.json); no arm is assigned to this card")
    return {
        "schema": "rosy.omx-task-card.v1", "task_id": task_id, "revision": 1,
        "single_task": f"Take the container from the belt pickup end and place it on ship hold h{hold}, {ROW_NAME[row]} (r{row}), "
                       f"{LAYER_NAME[layer]} (l{layer}).",
        "record": {"repo_id": f"local/omx-{task_id}", "root_prefix": root_prefix, "episode_time_s": 40, "reset_time_s": 10, "num_episodes": 5},
        "layout": layout,
        "known_limits": limits,
    }


def all_cards(root_prefix: str) -> list[dict]:
    return [card(h, r, l, root_prefix) for h in HOLDS for r in ROWS for l in LAYERS]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-prefix", default="/home/<user>/rosy-data/omx-leader")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for c in all_cards(args.root_prefix):
        (args.out / f"{c['task_id']}.yaml").write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")


if __name__ == "__main__":
    main()
