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
import math
from pathlib import Path

import cell_pipeline as cp
from cell_envelope import assess, digest, same_session
from cell_zones import Zones


class Gate:
    def __init__(self, cell, config: dict, calibration: dict, *, sequence=cp.SEQUENCE):
        self.cell, self.config, self.calibration, self.assessment = cell, config, calibration, None
        self.sequence, self.source, self.home = sequence, {}, None
        self._lib_cache: dict[tuple[str, int, int], tuple[dict, str]] = {}
        # two arms, one pallet (cell_zones): a reach claims its zone before it moves and frees it once folded home
        self.zones = Zones(config, calibration) if config.get("zone_side") else None

    def _load_library(self, library) -> tuple[dict, str]:
        if isinstance(library, dict):
            return library, digest(library)
        p = Path(library)
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        cached = self._lib_cache.get(key)
        if cached is None:
            loaded = json.loads(p.read_text())
            cached = (loaded, digest(loaded))
            self._lib_cache[key] = cached
        return cached

    def _assess(self, library, state: dict | None = None) -> dict:
        loaded, lib_sha = self._load_library(library)
        return assess(self.config, self.calibration, loaded,
                      self.cell.act("state") if state is None else state,
                      sequence=self.sequence, library_sha256=lib_sha)

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
        state, recovering = self.cell.act("state"), command.split()[0] in ("retreat", "park")
        lib_sha = None
        if command.startswith("load "):
            library, lib_sha = self._load_library(command[5:])
            self.source = library.get("source") or {}
            # The unchanged reviewed carry already owns its durable pending intent.
            identical = (self.assessment["mode"] == "automatic"
                         and digest([self.config, self.calibration, self.sequence]) == self.scope_sha
                         and lib_sha == self.assessment["library_sha256"])
            if not identical:
                fresh = self._assess(library, state=state)
                if not fresh["allowed"] or fresh["mode"] != self.assessment["mode"]:
                    return {"ok": False, "error": f"held: {fresh['reason']}", "envelope": fresh}
                fresh["session_id"] = self.assessment["session_id"]
                self.assessment = fresh
        if not same_session(state, self.assessment, recovering=recovering):
            faulted = state.get("fault") and same_session(state, self.assessment, recovering=True)
            return {"ok": False, "error": "held: fault" if faulted else "held: session_changed"}
        a = self.assessment
        if self.zones:
            self.zones.bind(a.get("operating_profile"), a["session_id"])
        sub_commands = [s.strip() for s in command[6:].split(";") if s.strip()] if command.startswith("chain ") else [command]
        for sub in sub_commands:
            target = {"goto above_pick": "pick", "goto above_place": "place"}.get(sub)
            if self.zones and target:
                xy = self.source.get(target) or {}
                allowed, why = self.zones.enter((xy["x"], xy["y"])) if "x" in xy else (False, f"library names no {target} point")
                if not allowed:
                    return {"ok": False, "error": f"held: zone: {why}"}
        status = self.cell.act(f"checked {a['session_id']} {a['library_sha256']} {command}")
        if command.startswith("load ") and status.get("ok"):
            self.home = ((library.get("chunks", {}).get("home") or [None])[-1]
                         if lib_sha == a["library_sha256"] else None)
        if self.zones and sub_commands and sub_commands[-1] == "park":
            from chunk_runner import SETTLE_TOL

            present, home = status.get("state"), self.home
            # Runner timeouts report ok=True; only measured, settled home clears physical occupancy.
            confirmed = (status.get("ok") is True and status.get("settled") is True and not status.get("fault")
                         and same_session(status, a)
                         and isinstance(present, list) and isinstance(home, list) and len(present) == len(home) == 6
                         and all(type(v) in (int, float) and math.isfinite(v) for v in present[:5] + home[:5])
                         and all(abs(p - h) <= SETTLE_TOL for p, h in zip(present[:5], home[:5])))
            if confirmed:
                self.zones.leave()
            elif status.get("ok"):
                return {**status, "ok": False, "error": "held: park_home_unconfirmed; zone reservations retained"}
        return status

    def frame(self, camera: str):
        return self.cell.frame(camera)


FOLDED = ("goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick", "park",
          "goto above_place", "run descend_place", "run release_place", "run lift_place", "park")

# jaws folded home on nothing stop about 2 units above the closed command (48.6 for 46.6); on a 30 mm box near 52.6
STILL_HOLDING_UNITS = 4.0


def transfer_folded(cell, library, closed: float | None = None, wrist=None, after_place=None, pinch=None, feel=None,
                    sequence=FOLDED, lift_stall=None, at_stop=None, grasp_check=None) -> dict:
    """cell_pipeline.transfer with a fold home between lift and place. Lifting a held box from the reach straight
    to the transit height took shoulder_lift to 525 of 600 and the runner's strain hold stopped it; folding home
    first and placing from home went clean twice (2026-10-28). `cell` is a Gate on the real arm. at_stop
    (cell_hooks.Stills) keeps every stop's frames before the arm moves on, a finished pick descent as its control, and is
    closed however the carry ends."""
    try:
        return _transfer(cell, library, closed, wrist, after_place, pinch, feel, sequence, lift_stall, at_stop, grasp_check)
    finally:
        if hasattr(at_stop, "close"):
            at_stop.close()


def _transfer(cell, library, closed, wrist, after_place, pinch, feel, sequence, lift_stall, at_stop, grasp_check=None) -> dict:
    steps = []
    if closed is None:  # 2026-11-13 arm_s: judged against the 46.5 command, empty jaws at 50.0 counted as holding
        try:
            closed = json.loads(Path(library).read_text()).get("jaw_empty_stop")
        except (OSError, ValueError):
            closed = None

    def run(command):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        return status

    for command in (f"load {library}", *sequence):  # FOLDED, or cp.SEQUENCE where auto.fold_before_transport is 0
        status = run(command)
        if not status.get("ok") and command == "goto above_pick" and "must park before recovery" in (status.get("error") or ""):
            if run("park").get("ok"):
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
        if status.get("contact") and at_stop is not None:  # the stop as it stands, before a retreat or a release hides it
            at_stop(status.get("state"), status)
        if status.get("contact") and command == "run lift_pick" and lift_stall is not None:
            # 2026-11-07: the retreat pressed the held box down (lag 2.54) and the park then refused to close on it
            freed = lift_stall(cell)
            steps.append({"command": "release and rise", **freed})
            parked = freed["result"] == "risen" and run("park").get("ok")
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error"), "released": bool(parked)}
        if status.get("contact"):  # the runner held with torque on: back up the same path (unless shedding), fold home
            if "overload-hold" not in (status.get("error") or ""):
                run("retreat")
            for _ in range(4):
                parked = run("park")
                if parked.get("ok") or "shedding its load" not in (parked.get("error") or ""):
                    break
                cp.time.sleep(1.0)
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error")}
        if not status.get("ok"):
            if not status.get("fault") and command not in ("park", f"load {library}"):
                run("park")
            return {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps}
        if command == "goto above_pick" and wrist is not None:  # cell_hooks: reach and wrist corrections before the descent
            aligned = wrist()
            steps.append({"command": "wrist", **{k: aligned.get(k) for k in ("verdict", "dx_mm", "dy_mm", "total_mm", "hooks")}})
            if aligned["verdict"] == "refuse":
                run("park")
                return {"result": "misaligned", "at": "wrist", "wrist": aligned, "steps": steps}
        if command == "run descend_pick" and hasattr(at_stop, "control"):  # reached the grasp height: met nothing
            at_stop.control(status)
        if command == "run descend_pick" and pinch is not None:  # cell_pinch: lowered, is the box between the fingers?
            seen = pinch()
            steps.append({"command": "pinch", **{k: seen.get(k) for k in ("verdict", "why", "dx_mm", "dy_mm")}})
            if seen["verdict"] == "refuse":
                run("run lift_pick"), run("park")
                return {"result": "misaligned", "at": "pinch", "pinch": seen, "steps": steps}
        if command == "run lift_place" and status.get("ok") and after_place is not None:
            after_place()  # hover over the box just placed: the wrist reference for 'centred' (cell_wrist_ref)
        if command in ("run grasp_pick", "run lift_pick") and not status.get("holding"):
            import cell_arm_cal

            if cell_arm_cal.infer_holding(status, closed=closed if closed is not None else 48.8):
                status["holding"] = True
                status["holding_inferred"] = True
        if command == "run grasp_pick" and not status.get("holding") and feel is not None:
            status = feel(run)  # cell_feel: an empty grasp feels again, shifted along the closing axis
            if status.get("contact") or not status.get("ok"):
                run("retreat"), run("park")
                return {"result": "contact" if status.get("contact") else "refused", "at": "feel", "steps": steps}
        if command == "run grasp_pick" and not status.get("holding"):
            for after in ("run lift_pick", "park"):
                run(after)
            return {"result": "empty", "at": command, "steps": steps}
        if command in ("run lift_pick", "park", "goto above_place", "run descend_place") and status.get("holding") is False:
            if command != "park":
                run("park")
            return {"result": "empty", "at": command, "steps": steps}
        if command in ("run grasp_pick", "run lift_pick") and status.get("holding") and grasp_check is not None:
            checked = grasp_check(command, status, run)
            steps.append({"command": "grasp_debate", "at": command, **{k: checked.get(k) for k in ("verdict", "recovery_chunk", "dx_mm", "dy_mm", "reason", "telemetry", "vision", "debate")}})
            if checked.get("verdict") == "reinsert_and_park":
                run("park")
                return {"result": "reinserted", "at": command, "grasp_debate": checked, "steps": steps}
            if checked.get("verdict") == "reinsert_and_retry" and isinstance(checked.get("retry_status"), dict):
                status = checked["retry_status"]
                if not status.get("holding"):
                    run("park")
                    return {"result": "empty", "at": command, "grasp_debate": checked, "steps": steps}
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
