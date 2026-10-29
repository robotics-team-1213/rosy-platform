#!/usr/bin/env python3
"""The per-carry hooks of a pick, assembled in one place, in the order the carry runs them:

  above the box     cell_look (top camera: jaws vs box in one image) -> cell_reach (FK feed-forward)
                    -> cell_wrist_ref (reference servo) -> cell_fingers (finger servo)
                    -> cell_wrist (calibrated band)          one chain; the first refusal stops the descent
  after the descent cell_pinch (lower, then look: the box between the fingers)
  on an empty grasp cell_feel (feel along the closing axis)
  after a place     cell_wrist_ref.capture_reference (the wrist reference for 'centred')

Each is None when its parameter turns it off; cell_transfer.transfer_folded runs them through the D-911 gate.
"""
from __future__ import annotations

from pathlib import Path

import cell_feel
import cell_fingers
import cell_look
import cell_params as prm
import cell_pinch
import cell_reach
import cell_wrist
import cell_wrist_ref


def pick_hooks(config: dict, cell, target: dict, write_library, source: str, dest_site: str, emit=None, calibration=None):
    """(hover hook chain, after-place reference capture, after-descent pinch check, empty-grasp feel search) for one
    pick; None where off.
    `config` carries the pick's own plan values (jaw opening): the gap between the open pads comes from it."""

    params, spec = config.get("params"), config.get("wrist") or {}
    gap = 30.0 + (config["plan"]["grip_open"] - prm.get(params, "gripper.held_30mm")) * prm.get(params, "gripper.gap_mm_per_unit")
    wrist = cell_reach.chain(cell_look.hook(config, cell, target, write_library, calibration, source),
                             cell_reach.hook(config, cell, target, write_library),
                             cell_wrist_ref.ref_hook(config, cell, target, write_library, source),
                             cell_fingers.finger_hook(config, cell, target, write_library, gap),
                             cell_wrist.hook(config, cell, target, write_library, emit))
    capture = None
    if prm.get(params, "wrist.ref_servo") and spec.get("hsv_min"):
        work, arm = Path(config["work_dir"]).expanduser(), config.get("arm_id", "arm_s")
        capture = lambda: cell.act("goto above_place").get("ok") and cell_wrist_ref.capture_reference(  # noqa: E731
            cell, spec.get("camera", "wrist"), (spec["hsv_min"], spec["hsv_max"]), work, arm, dest_site, params)
    return (wrist, capture, cell_pinch.hook(config, cell, target, write_library, gap, target["entry"]["width_mm"]),
            cell_feel.feel_hook(config, cell, target, write_library))
