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
from cell_policy_timing import cmd_ack_ok, park_ack_ok, retreat_ack_ok
from cell_zones import Zones


class Gate:
    def __init__(self, cell, config: dict, calibration: dict, *, sequence=cp.SEQUENCE):
        self.cell, self.config, self.calibration, self.assessment = cell, config, calibration, None
        self.sequence, self.source, self.home, self.rehome = sequence, {}, None, None
        self.before_motion, self.finish_attempt = None, None
        self.history, self.transitions, self.finalized, self.blocked = [], 0, False, False
        self._lib_cache: dict[tuple[str, int, int], tuple[dict, str]] = {}
        # two arms, one pallet (cell_zones): a reach claims its zone before it moves and frees it once folded home
        self.zones = Zones(config, calibration) if config.get("zone_side") else None
        if callable(getattr(cell, "frame_receipt", None)): self.frame_receipt = cell.frame_receipt
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

    def _assess(self, library, state: dict | None = None, **checks) -> dict:
        loaded, lib_sha = self._load_library(library)
        return assess(self.config, self.calibration, loaded,
                      self.cell.act("state") if state is None else state,
                      sequence=self.sequence, library_sha256=lib_sha, **checks)

    def open(self, library, before_motion, finish_attempt=None) -> dict | None:
        """None when the carry may start (the intent is written first); else the held envelope."""
        from cell_unwedge import can_rehome, rehome_before_work

        loaded, _ = self._load_library(library)
        state = self.cell.act("state")
        self.assessment = self._assess(loaded, state=state)
        if not self.assessment["allowed"] and self.assessment["reason"] != "start_not_home":
            return self.assessment
        home = (loaded.get("chunks", {}).get("home") or [None])[-1]
        rehome_allowed = can_rehome(state, home)
        needs_home = self.assessment["reason"] == "start_not_home"
        if needs_home and rehome_allowed:
            self.assessment = self._assess(loaded, state=state, check_home=False)
        if not self.assessment["allowed"]:
            return self.assessment
        self.scope_sha = digest([self.config, self.calibration, self.sequence])
        try:
            intent = before_motion(self.assessment)
            if intent is None and self.assessment["mode"] == "automatic":
                raise OSError("automatic rehome requires a durable intent")
        except OSError:
            return {**self.assessment, "allowed": False, "reason": "audit_unavailable"}
        self.before_motion, self.finish_attempt = before_motion, finish_attempt
        if not rehome_allowed:  # commissioning keeps no ledger (intent None) and still rehomes, as #263 did
            return None
        self.rehome = rehome_before_work(self.cell, loaded, self.config, assessment=self.assessment,
                                        required=needs_home)
        try:
            if self.rehome is not None and self.config.get("work_dir"):
                cp.write_receipt(Path(self.config["work_dir"]).expanduser() / "receipts", "rehome", self.rehome)
        except OSError:
            self.blocked = True
            return {**self.assessment, "allowed": False, "reason": "audit_unavailable"}
        if self.rehome is not None:
            result = self.rehome["result"]
            if result == "session_changed" or (result != "home" and self.rehome_started):
                self.blocked = True
                reason = result if result == "session_changed" else f"rehome_{result}"
                return {**self.assessment, "allowed": False, "reason": reason}
            try:
                fresh = self._assess(library, allow_pending=intent if isinstance(intent, dict) else None)
            except (OSError, ValueError, TypeError):
                fresh = {**self.assessment, "allowed": False, "reason": "evidence_unavailable"}
            if fresh != self.assessment:
                self.blocked = True
                return {**fresh, "allowed": False, "reason": "session_changed" if fresh["allowed"] else fresh["reason"]}
        return None

    @property
    def rehome_started(self) -> bool:
        receipt = self.rehome or {}
        return bool(receipt.get("plan") or receipt.get("jogs") or receipt.get("stop"))

    def _settled_home(self, status, assessment) -> bool:
        from chunk_runner import SETTLE_TOL

        present, home = status.get("state"), self.home
        return (status.get("ok") is True and status.get("settled") is True and not status.get("fault")
                and same_session(status, assessment)
                and isinstance(present, list) and isinstance(home, list) and len(present) == len(home) == 6
                and all(type(v) in (int, float) and math.isfinite(v) for v in present[:5] + home[:5])
                and all(abs(p - h) <= SETTLE_TOL for p, h in zip(present[:5], home[:5])))

    def act(self, command: str) -> dict:
        if command in ("state", "human-hold"):
            return self.cell.act(command)
        if self.blocked:
            return {"ok": False, "error": "held: audit_transition_incomplete"}
        state, recovering = self.cell.act("state"), command.split()[0] in ("retreat", "park")
        lib_sha = None
        if command.startswith("load "):
            library, lib_sha = self._load_library(command[5:])
            self.source = library.get("source") or {}
            identical = (digest([self.config, self.calibration, self.sequence]) == self.scope_sha
                         and lib_sha == self.assessment["library_sha256"])
            if not identical:
                if digest([self.config, self.calibration, self.sequence]) != self.scope_sha:
                    return {"ok": False, "error": "held: reviewed_scope_changed"}
                if self.assessment["mode"] != "commissioning" or self.finish_attempt is None:
                    return {"ok": False, "error": "held: revised_library_requires_supervised_audit"}
                if self.transitions >= 4:
                    return {"ok": False, "error": "held: replan_limit_reached"}
                fresh = self._assess(library, state=state)
                if not fresh["allowed"] or fresh["mode"] != self.assessment["mode"]:
                    return {"ok": False, "error": f"held: {fresh['reason']}", "envelope": fresh}
                old = self.assessment
                parked = self.act("park")
                if not self._settled_home(parked, old):
                    self.blocked = True
                    return {"ok": False, "error": "held: revised_library_home_unconfirmed"}
                try:
                    self.finish_attempt("replanned", old, parked, self.history)
                except Exception:
                    self.blocked = True
                    return {"ok": False, "error": "held: audit_unavailable"}
                self.finalized, self.history, fresh["session_id"] = True, [], old["session_id"]
                try:
                    self.before_motion(fresh)
                except Exception:
                    self.blocked = True
                    return {"ok": False, "error": "held: audit_unavailable"}
                self.assessment, self.finalized, self.transitions = fresh, False, self.transitions + 1
                state = self.cell.act("state")
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
        status = {**status, "pre_state_trace": {"t": state.get("t"), "trace_receipt": state.get("trace_receipt")}}
        self.history.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if command.startswith("load ") and status.get("ok"):
            self.home = ((library.get("chunks", {}).get("home") or [None])[-1]
                         if lib_sha == a["library_sha256"] else None)
        if command.startswith("load ") and not status.get("ok") and self.transitions:
            try:
                self.finish_attempt("load_refused", a, status, self.history)
                self.finalized = True
            except Exception:
                status = {**status, "error": "held: audit_unavailable"}
            self.blocked = True
        if self.zones and sub_commands and sub_commands[-1] == "park":
            from chunk_runner import SETTLE_TOL

            # Runner timeouts report ok=True; only measured, settled home clears physical occupancy.
            confirmed = self._settled_home(status, a)
            if confirmed:
                self.zones.leave()
            elif status.get("ok"):
                return {**status, "ok": False, "error": "held: park_home_unconfirmed; zone reservations retained"}
        return status

    def frame(self, camera: str):
        return self.cell.frame(camera)


FOLDED = ("goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick", "park",
          "goto above_place", "run descend_place", "run release_place", "run lift_place", "park")
RETURN_HELD = ("goto above_place", "run descend_place", "run release_place", "run lift_place", "park")

# jaws folded home on nothing stop about 2 units above the closed command (48.6 for 46.6); on a 30 mm box near 52.6
STILL_HOLDING_UNITS = 4.0


def _motion_ack_ok(reply, command: str, *, strict: bool) -> bool:
    if strict:
        return cmd_ack_ok(reply, (command, f"run {command}"), require_command=True)
    if (not isinstance(reply, dict) or reply.get("ok") is not True
            or any(reply.get(k) for k in ("fault", "hold", "human_hold_latched"))
            or reply.get("settled") is False):
        return False
    if "command" in reply:
        cmd = str(reply["command"])
        return (cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd) in (command, f"run {command}")
    return True


def _park_ok(reply, *, strict: bool) -> bool:
    return cmd_ack_ok(reply, ("park", "run park"), require_command=True) if strict else park_ack_ok(reply)


def _retreat_ack_ok(reply, *, strict: bool) -> bool:
    return retreat_ack_ok(reply) if strict else _motion_ack_ok(reply, "retreat", strict=False)


def transfer_folded(cell, library, closed: float | None = None, wrist=None, after_place=None, pinch=None, feel=None,
                    sequence=FOLDED, lift_stall=None, at_stop=None, grasp_check=None, *, strict_motion: bool = False) -> dict:
    """cell_pipeline.transfer with a fold home between lift and place. Lifting a held box from the reach straight
    to the transit height took shoulder_lift to 525 of 600 and the runner's strain hold stopped it; folding home
    first and placing from home went clean twice (2026-10-28). `cell` is a Gate on the real arm. at_stop
    (cell_hooks.Stills) keeps every stop's frames before the arm moves on, a finished pick descent as its control, and is
    closed however the carry ends."""
    try:
        return _transfer(cell, library, closed, wrist, after_place, pinch, feel, sequence, lift_stall, at_stop, grasp_check, strict_motion=strict_motion)
    finally:
        if hasattr(at_stop, "close"):
            at_stop.close()


def _transfer(cell, library, closed, wrist, after_place, pinch, feel, sequence, lift_stall, at_stop, grasp_check=None, *, strict_motion: bool = False) -> dict:
    steps = []
    release_completed = False
    if closed is None:  # 2026-11-13 arm_s: judged against the 46.5 command, empty jaws at 50.0 counted as holding
        try:
            _lib = json.loads(Path(library).read_text())
            closed = _lib.get("jaw_empty_stop") if _lib.get("jaw_empty_stop") is not None else _lib.get("gripper_closed")
        except (OSError, ValueError):
            closed = None

    def run(command):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if command in ("run release_place", "run lift_place") and status.get("trace_receipt"):
            steps[-1]["trace_receipt"] = status["trace_receipt"]  # byte range of the owner trace: release evidence only
        return status

    def _fault(at, reply, fallback):
        return {"result": "fault", "at": at, "steps": steps, "error": (reply.get("error") if isinstance(reply, dict) else None) or fallback}

    def _seq_ok(cmds):
        for c in cmds:
            r = run(c)
            if strict_motion and not (_park_ok(r, strict=True) if c == "park" else _motion_ack_ok(r, c, strict=True)):
                return _fault(c, r, f"{c} unconfirmed")
        return None

    for command in (f"load {library}", *sequence):  # FOLDED, or cp.SEQUENCE where auto.fold_before_transport is 0
        status = run(command)
        if not status.get("ok") and command in ("goto above_pick", "goto above_place") and "must park before recovery" in (status.get("error") or ""):
            if _park_ok(parked := run("park"), strict=strict_motion):
                status = run(command)
            elif strict_motion:
                return _fault("park", parked, "recovery park unconfirmed")
        if isinstance(status, dict) and ("release not confirmed" in str(status.get("error") or "") or (command == "run release_place" and status.get("holding") is True)) and (strict_motion or status.get("ok") is not True):
            return _fault(command, status, "release not confirmed")
        if status.get("contact") and command == "park":
            # a fold's strain hold at the reach: back off and fold again (home in runs 3-4, 2026-10-28); a second stops
            if "overload-hold" not in (status.get("error") or ""):  # a shed load sags: no backing up from there
                retreated = run("retreat")
                if not _retreat_ack_ok(retreated, strict=strict_motion):
                    return _fault("retreat", retreated, "retreat unconfirmed")
                status = run("park")
                if _park_ok(status, strict=strict_motion):
                    continue
                if strict_motion:
                    return _fault("park", status, "retry park unconfirmed")
        if status.get("contact") and command == "run lift_place":
            if strict_motion:
                return _fault(command, status, "contact during lift_place")
            # strain after release: backing up brings the open jaws round the box again (2026-10-28 Pinky); fold from here
            if "overload-hold" not in (status.get("error") or "") and park_ack_ok(run("park")):
                continue
            return _fault(command, status, "lift_place park unconfirmed")
        if status.get("contact") and at_stop is not None:  # the stop as it stands, before a retreat or a release hides it
            at_stop(status.get("state"), status)
        if status.get("contact") and command == "run lift_pick" and lift_stall is not None:
            # 2026-11-07: the retreat pressed the held box down (lag 2.54) and the park then refused to close on it
            freed = lift_stall(cell)
            steps.append({"command": "release and rise", **freed})
            parked = freed["result"] == "risen" and _park_ok(run("park"), strict=strict_motion)
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error"), "released": bool(parked)}
        if status.get("contact"):  # the runner held with torque on: back up the same path (unless shedding), fold home
            if "overload-hold" not in (status.get("error") or ""):
                retreated = run("retreat")
                if not _retreat_ack_ok(retreated, strict=strict_motion):
                    return _fault("retreat", retreated, "retreat unconfirmed")
            elif strict_motion:
                return {"result": "contact", "at": command, "steps": steps, "error": status.get("error")}
            parked = None
            for _ in range(4):
                parked = run("park")
                if parked.get("ok") or "shedding its load" not in (parked.get("error") or ""):
                    break
                cp.time.sleep(1.0)
            if strict_motion and not _park_ok(parked, strict=True):
                return _fault("park", parked, "recovery park unconfirmed")
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error")}
        is_motion = not command.startswith("load ")
        cmd_ok = (_park_ok(status, strict=strict_motion) if command == "park" else
                  _motion_ack_ok(status, command, strict=strict_motion) if is_motion else
                  bool(isinstance(status, dict) and status.get("ok") is True and not any(status.get(k) for k in ("fault", "hold", "human_hold_latched"))))
        if not cmd_ok:
            lost_reply = isinstance(status, dict) and str(status.get("error") or "").startswith("no status within")
            unconfirmed_motion = is_motion and isinstance(status, dict) and status.get("ok") is True and not cmd_ok
            hard_fail = bool(not isinstance(status, dict) or status.get("fault") or status.get("hold") or status.get("human_hold_latched")
                             or status.get("settled") is False or lost_reply or unconfirmed_motion)
            if not hard_fail and command not in ("park", f"load {library}"):
                if (flt := _seq_ok(("park",))):
                    return flt
            err_msg = (status.get("error") if isinstance(status, dict) else None) or (f"{command} did not settle" if unconfirmed_motion else None)
            return {"result": "fault" if hard_fail else "refused", "at": command, "steps": steps, **({"error": err_msg} if err_msg else {})}
        if command == "goto above_pick" and wrist is not None:  # cell_hooks: reach and wrist corrections before the descent
            aligned = wrist()
            steps.append({"command": "wrist", **{k: aligned.get(k) for k in ("verdict", "dx_mm", "dy_mm", "total_mm", "hooks")}})
            if aligned["verdict"] == "refuse":
                return _seq_ok(("park",)) or {"result": "misaligned", "at": "wrist", "wrist": aligned, "steps": steps}
        if command == "run descend_pick" and hasattr(at_stop, "control"):  # reached the grasp height: met nothing
            at_stop.control(status)
        if command == "run descend_pick" and pinch is not None:  # cell_pinch: lowered, is the box between the fingers?
            seen = pinch()
            steps.append({"command": "pinch", **{k: seen.get(k) for k in ("verdict", "why", "dx_mm", "dy_mm")}})
            if seen["verdict"] == "refuse":
                return _seq_ok(("run lift_pick", "park")) or {"result": "misaligned", "at": "pinch", "pinch": seen, "steps": steps}
        if command == "run lift_place" and status.get("ok") and after_place is not None:
            after_place()  # hover over the box just placed: the wrist reference for 'centred' (cell_wrist_ref)
        no_pick = "run grasp_pick" not in sequence
        if (
            command in ("run grasp_pick", "run lift_pick")
            or (no_pick and command in ("goto above_place", "run descend_place"))
        ) and not status.get("holding"):
            import cell_arm_cal

            if cell_arm_cal.infer_holding(status, closed=closed if closed is not None else 48.8):
                status["holding"] = True
                status["holding_inferred"] = True
            elif no_pick and status.get("holding") is None:
                status["holding"] = False
        if command == "run grasp_pick" and not status.get("holding") and feel is not None:
            status = feel(run)  # cell_feel: an empty grasp feels again, shifted along the closing axis
            if status.get("contact") or not status.get("ok"):
                if "overload-hold" not in (status.get("error") or "") and _retreat_ack_ok(run("retreat"), strict=strict_motion):
                    if (flt := _seq_ok(("park",))):
                        return flt
                elif strict_motion:
                    return _fault("feel", status, "feel recovery unconfirmed")
                return {"result": "contact" if status.get("contact") else "refused", "at": "feel", "steps": steps}
        if command == "run grasp_pick" and not status.get("holding"):
            return _seq_ok(("run lift_pick", "park")) or {"result": "empty", "at": command, "steps": steps}
        if command == "run release_place":
            release_completed = True
        if (not release_completed and command in ("run lift_pick", "park", "goto above_place", "run descend_place")
                and status.get("holding") is False):
            return (_seq_ok(("park",)) if command != "park" else None) or {"result": "empty", "at": command, "steps": steps}
        if command in ("run grasp_pick", "run lift_pick") and status.get("holding") and grasp_check is not None:
            checked = grasp_check(command, status, run)
            steps.append({"command": "grasp_debate", "at": command, **{k: checked.get(k) for k in ("verdict", "recovery_chunk", "dx_mm", "dy_mm", "reason", "telemetry", "vision", "debate")}})
            if checked.get("verdict") == "empty":
                # 2026-11-17 arm_s floor: jaws closed on air (48.91, empty stop 49.0) passed the runner's holding test,
                # the debate said "empty" twice, and the carry still went on to the belt
                return _seq_ok(("run lift_pick", "park") if command == "run grasp_pick" else ("park",)) or {"result": "empty", "at": command, "grasp_debate": checked, "steps": steps}
            if checked.get("verdict") == "reinsert_and_park":
                return _seq_ok(("park",)) or {"result": "reinserted", "at": command, "grasp_debate": checked, "steps": steps}
            if checked.get("verdict") == "reinsert_and_retry" and isinstance(checked.get("retry_status"), dict):
                status = checked["retry_status"]
                if not status.get("holding"):
                    return _seq_ok(("park",)) or {"result": "empty", "at": command, "grasp_debate": checked, "steps": steps}
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
