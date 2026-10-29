#!/usr/bin/env python3
"""The folded carry (pick, fold home, place) behind the reviewed operating envelope (D-911).

Gate wraps the cell for one carry: every command but `state` goes `checked` against the assessment of the library
the runner holds, so an unchecked command cannot slip into the chain, and a `load` - a hook's re-plan (reach, wrist,
pinch, feel) - is assessed before it is sent and refused unless allowed in the same mode. In automatic mode that holds
any path a person has not reviewed exactly; supervised trials run with config["_commissioning"] (cell_auto_pick
--commissioning --person-at-switch), one stage at a time, never the role loop.
"""
from __future__ import annotations

import json
from pathlib import Path

import cell_pipeline as cp
from cell_envelope import assess, digest, same_session


class Gate:
    def __init__(self, cell, config: dict, calibration: dict, *, sequence=cp.SEQUENCE):
        self.cell, self.config, self.calibration, self.assessment = cell, config, calibration, None
        self.sequence = sequence

    def _assess(self, library) -> dict:
        return assess(self.config, self.calibration, json.loads(Path(library).read_text()), self.cell.act("state"),
                      sequence=self.sequence)

    def open(self, library, before_motion) -> dict | None:
        """None when the carry may start (the intent is written first); else the held envelope."""
        self.assessment = self._assess(library)
        if not self.assessment["allowed"]:
            return self.assessment
        self.scope_sha = digest([self.config, self.calibration, self.sequence])
        try:
            before_motion(self.assessment)
        except OSError:
            return {**self.assessment, "allowed": False, "reason": "audit_unavailable"}
        return None

    def act(self, command: str) -> dict:
        if command == "state":
            return self.cell.act(command)
        if command.startswith("load "):
            # The unchanged reviewed carry already owns its durable pending intent.
            identical = (self.assessment["mode"] == "automatic"
                         and digest([self.config, self.calibration, self.sequence]) == self.scope_sha
                         and digest(json.loads(Path(command[5:]).read_text())) == self.assessment["library_sha256"])
            if not identical:
                fresh = self._assess(command[5:])
                if not fresh["allowed"] or fresh["mode"] != self.assessment["mode"]:
                    return {"ok": False, "error": f"held: {fresh['reason']}", "envelope": fresh}
                fresh["session_id"] = self.assessment["session_id"]
                self.assessment = fresh
        if not same_session(self.cell.act("state"), self.assessment):
            return {"ok": False, "error": "held: session_changed"}
        a = self.assessment
        return self.cell.act(f"checked {a['session_id']} {a['library_sha256']} {command}")

    def frame(self, camera: str):
        return self.cell.frame(camera)


FOLDED = ("goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick", "park",
          "goto above_place", "run descend_place", "run release_place", "run lift_place", "park")

# jaws folded home on nothing stop about 2 units above the closed command (48.6 for 46.6); on a 30 mm box near 52.6
STILL_HOLDING_UNITS = 4.0


def transfer_folded(cell, library, closed: float | None = None, wrist=None, after_place=None, pinch=None, feel=None,
                    sequence=FOLDED) -> dict:
    """cell_pipeline.transfer with a fold home between lift and place. Lifting a held box from the reach straight
    to the transit height took shoulder_lift to 525 of 600 and the runner's strain hold stopped it; folding home
    first and placing from home went clean twice (2026-10-28). `cell` is a Gate on the real arm."""
    steps = []

    def run(command):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        return status

    for command in (f"load {library}", *sequence):  # FOLDED, or cp.SEQUENCE where auto.fold_before_transport is 0
        status = run(command)
        if status.get("contact") and command == "park":
            # a fold's strain hold at the reach: back off and fold again (home in runs 3-4, 2026-10-28); a second stops
            run("retreat")
            status = run("park")
            if status.get("ok"):
                continue
        if status.get("contact") and command == "run lift_place":
            # strain after release: backing up brings the open jaws round the box again (2026-10-28 Pinky); fold from here
            run("park")
            continue
        if status.get("contact"):  # the runner held with torque on: back up the same path, fold home
            for after in ("retreat", "park"):
                run(after)
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error")}
        if not status.get("ok"):
            if not status.get("fault") and command not in ("park", f"load {library}"):
                run("park")
            return {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps}
        if command == "goto above_pick" and wrist is not None:  # cell_hooks: reach and wrist corrections before the descent
            aligned = wrist()
            steps.append({"command": "wrist", **{k: aligned[k] for k in ("verdict", "dx_mm", "dy_mm", "total_mm")}})
            if aligned["verdict"] == "refuse":
                run("park")
                return {"result": "misaligned", "at": "wrist", "wrist": aligned, "steps": steps}
        if command == "run descend_pick" and pinch is not None:  # cell_pinch: lowered, is the box between the fingers?
            seen = pinch()
            steps.append({"command": "pinch", **{k: seen.get(k) for k in ("verdict", "why", "dx_mm", "dy_mm")}})
            if seen["verdict"] == "refuse":
                run("run lift_pick"), run("park")
                return {"result": "misaligned", "at": "pinch", "pinch": seen, "steps": steps}
        if command == "run lift_place" and status.get("ok") and after_place is not None:
            after_place()  # hover over the box just placed: the wrist reference for 'centred' (cell_wrist_ref)
        if command == "run grasp_pick" and not status.get("holding") and feel is not None:
            status = feel(run)  # cell_feel: an empty grasp feels again, shifted along the closing axis
            if status.get("contact") or not status.get("ok"):
                run("retreat"), run("park")
                return {"result": "contact" if status.get("contact") else "refused", "at": "feel", "steps": steps}
        if command == "run grasp_pick" and not status.get("holding"):
            for after in ("run lift_pick", "park"):
                run(after)
            return {"result": "empty", "at": command, "steps": steps}
    if closed is None:
        try:
            closed = json.loads(Path(library).read_text())["gripper_closed"]
        except (OSError, ValueError, KeyError):
            closed = None
    jaws = (status.get("state") or [None] * 6)[5]
    if closed is not None and jaws is not None and jaws > closed + STILL_HOLDING_UNITS:
        # 2026-10-28: a low lift after the release let the park's closing jaws take the box back; "placed" was wrong
        return {"result": "still holding", "at": "park", "jaws": jaws, "steps": steps}
    return {"result": "placed", "steps": steps}
