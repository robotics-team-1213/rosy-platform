#!/usr/bin/env python3
"""The per-carry hooks of a pick, assembled in one place, in the order the carry runs them:

  above the box     cell_reach (FK feed-forward) -> cell_look (top camera: jaws vs box in one image, last word on
                    position) -> cell_wrist_ref (reference servo) -> cell_fingers (finger servo)
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


class Stills:
    """At any guard stop, before the arm backs out and hides it: one frame per camera (top, side, the arm's wrist), kept as
    <arm>-<camera>.jpg; the incident report carries them (D-971). 11-06/07: the descent contacts kept none, only a lift stall
    did, and the frames taken after the fold could not tell contact from speed. With config `tip_view` and the stopped joints,
    also <arm>-<camera>-tip.jpg: the crop around the jaw tip (cell_tip_view). With config `evidence`, a ring of every camera
    for the carry and, at the stop, one hashed bundle of the seconds around it; a finished pick descent is kept once per
    carry the same way, as a control (cell_evidence). close() ends the ring and waits for the bundles. Reads only."""

    def __init__(self, cell, config: dict):
        self.cell, self.config, self.arm, self.writers, self.controlled = cell, config, config.get("arm_id", "arm_s"), [], False
        self.ring = None
        if config.get("evidence") is not None:
            import cell_evidence as ev

            spec = config["evidence"]
            self.ring = ev.Ring(cell.frame, config["cameras"], spec.get("period_s", ev.PERIOD_S), spec.get("keep_s", ev.KEEP_S))

    def __call__(self, state=None, status=None):
        import cv2

        import omx_incident

        folder, frames, tips = Path(omx_incident.STILLS), {}, {}
        folder.mkdir(parents=True, exist_ok=True)
        for camera in self.config["cameras"]:
            try:
                frames[camera] = self.cell.frame(camera)
                cv2.imwrite(str(folder / f"{self.arm}-{camera}.jpg"), frames[camera])
            except Exception:  # a missing frame must not stop the recovery
                pass
        if self.config.get("tip_view") and state:
            try:
                import cell_tip_view

                tips = cell_tip_view.tip_crops(frames, cell_tip_view.fk_tip(state), self.config["tip_view"])
                for camera, image in tips.items():
                    cv2.imwrite(str(folder / f"{self.arm}-{camera}-tip.jpg"), image)
            except Exception:  # nor a crop
                pass
        self.bundle("stop", state, status or {}, tips)

    def control(self, status: dict) -> None:
        """A pick descent that ran to its end: what the cameras saw with nothing in the way, once per carry."""
        if not self.controlled:
            self.controlled = True
            self.bundle("control", status.get("state"), status, {})

    def bundle(self, kind: str, state, status: dict, tips: dict) -> None:
        if self.ring is None:
            return
        import threading
        import time

        import cv2

        import cell_evidence as ev
        import omx_incident

        at = time.time()

        def write():  # after AFTER_S, while the retreat runs: the arm is never held for a picture
            try:
                time.sleep(ev.AFTER_S)
                frames, gaps = self.ring.window(at - self.ring.keep_s)
                files = {f"{camera}-tip.jpg": cv2.imencode(".jpg", image)[1].tobytes() for camera, image in tips.items()}
                files["trace-tail.jsonl"] = ev.trace_tail(self.arm)
                kept = {k: status.get(k) for k in ("command", "ok", "error", "contact", "fault", "state", "target")}
                ev.write(Path(omx_incident.INCIDENTS) / "evidence", kind, self.arm, at, frames, gaps, {"stop": kept, "state": state}, files)
            except Exception:  # evidence is never worth a failed carry
                pass
        self.writers.append(threading.Thread(target=write, daemon=True))
        self.writers[-1].start()

    def close(self) -> None:
        for writer in self.writers:
            writer.join(timeout=10)
        if self.ring is not None:
            self.ring.close()


def stills(cell, config: dict) -> Stills:
    return Stills(cell, config)


def lift_stall(cell, config: dict, sleep):
    """What a stop on the first lift does: let go and rise (cell_unwedge). Jogs leave the D-911 gate, so supervised only."""
    if config.get("_commissioning") != {"person_at_switch": True}:
        return None
    import cell_unwedge

    def stall(gate):  # the stop's frames are kept already (transfer_folded's at_stop)
        a = gate.assessment
        # an unchecked jog starts a new session, and the gate's fold after it would be refused with the arm out: same session, same
        # library, past the gate's fault hold only because a person is at the switch
        return cell_unwedge.release_and_rise(Checked(cell, a["session_id"], a["library_sha256"]), sleep=sleep)
    return stall


class Checked:
    """A cell whose commands other than state name the session and library they belong to (chunk_runner's `checked`)."""

    def __init__(self, cell, session_id: str, library_sha256: str):
        self.cell, self.prefix = cell, f"checked {session_id} {library_sha256} "

    def act(self, command: str) -> dict:
        return self.cell.act(command if command == "state" else self.prefix + command)


def pick_hooks(config: dict, cell, target: dict, write_library, source: str, dest_site: str, emit=None, calibration=None,
               guard=None):
    """(hover hook chain, after-place reference capture, after-descent pinch check, empty-grasp feel search) for one
    pick; None where off.
    `config` carries the pick's own plan values (jaw opening): the gap between the open pads comes from it."""

    params, spec = config.get("params"), config.get("wrist") or {}
    gap = 30.0 + (config["plan"]["grip_open"] - prm.get(params, "gripper.held_30mm")) * prm.get(params, "gripper.gap_mm_per_unit")
    later = [cell_wrist_ref.ref_hook(config, cell, target, write_library, source),
             cell_fingers.finger_hook(config, cell, target, write_library, gap),
             cell_wrist.hook(config, cell, target, write_library, emit)]
    # a look with no room to open the jaws is skipped only when one of these still measures the position
    wrist = cell_reach.chain(guard, cell_reach.hook(config, cell, target, write_library),
                             cell_look.hook(config, cell, target, write_library, calibration, source,
                                            fallback=any(h is not None for h in later)), *later)
    capture = None
    if prm.get(params, "wrist.ref_servo") and spec.get("hsv_min"):
        work, arm = Path(config["work_dir"]).expanduser(), config.get("arm_id", "arm_s")
        capture = lambda: cell.act("goto above_place").get("ok") and cell_wrist_ref.capture_reference(  # noqa: E731
            cell, spec.get("camera", "wrist"), (spec["hsv_min"], spec["hsv_max"]), work, arm, dest_site, params,
            target["entry"]["length_mm"] * target["entry"]["width_mm"])
    return (wrist, capture, cell_pinch.hook(config, cell, target, write_library, gap, target["entry"]["width_mm"]),
            cell_feel.feel_hook(config, cell, target, write_library))
