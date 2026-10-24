#!/usr/bin/env python3
"""Wrist-camera correction before a grasp, with each axis's image response measured first (probe).

2026-10-25 on arm S: a fixed rule (base minus moves the box right, reach forward makes it bigger) worked
over Pinky but was inverted over the belt, where the wrist is rolled about 113 degrees, and a learned
sign flip-flopped on noise. Here each correction axis is first nudged once and back; the measured change
of the box in the wrist view per joint unit then sets the direction and size of every step. Rotation is
matched first (the jaws close across the box), then left/right, then distance (by area, or by height
when the box runs off the top of the view). The grasp chunk runs relative, keeping the correction.

The executor is chunk_runner (judge commands); `act(command) -> status` and `observe() -> wrist box`
are injected, so the same loop runs against the real runner, a simulation, or a test.
"""
from __future__ import annotations

AXES = {  # axis -> (joint, sign) pairs moved together by one unit
    "pan": (("shoulder_pan.pos", 1),),
    "reach": (("shoulder_lift.pos", 1), ("elbow_flex.pos", -1)),
    "roll": (("wrist_roll.pos", 1),),
}
DEFAULTS = {"probe": {"pan": 1.0, "reach": 1.0, "roll": 2.0}, "max_step": {"pan": 2.0, "reach": 2.0, "roll": 4.0},
            "tolerance": {"pan_px": 25.0, "area": 0.15, "tilt_deg": 5.0, "cut_cy_px": 45.0},
            "min_response": {"pan": 4.0, "reach": 0.01, "roll": 0.5}, "max_steps": 20}


def jog(axis: str, units: float) -> str:
    return "jog " + " ".join(f"{name} {round(sign * units, 2)}" for name, sign in AXES[axis])


class Servo:
    def __init__(self, act, observe, site: dict, config: dict | None = None, log=lambda entry: None):
        self.act, self.observe, self.site, self.log = act, observe, site, log
        self.cfg = {k: (dict(v, **(config or {}).get(k, {})) if isinstance(v, dict) else (config or {}).get(k, v))
                    for k, v in DEFAULTS.items()}
        self.response: dict = {}

    def measures(self, box):
        """Errors against the site reference: (pan px, distance, tilt deg); distance is an area ratio - 1,
        or a height error in px when the box runs off the top edge."""
        ref = self.site
        dx = box["cx"] - ref["cx"]
        if box.get("cut_top"):
            distance = (box["cy"] - ref["cy"]) / 200.0  # higher in the view = farther, same sign as a small area
        else:
            distance = box["area"] / ref["area"] - 1.0
        tilt = None if box.get("tilt") is None or ref.get("tilt") is None else box["tilt"] - ref["tilt"]
        return dx, distance, tilt

    def probe(self):
        """Nudge each axis by +p and back; record the change of (pan px, distance, tilt) per unit."""
        for axis, units in self.cfg["probe"].items():
            before = self.observe()
            status = self.act(jog(axis, units))
            after = self.observe()
            self.act(jog(axis, -units))
            if not (status.get("ok") and before.get("found") and after.get("found")):
                self.response[axis] = None
                continue
            b, a = self.measures(before), self.measures(after)
            self.response[axis] = tuple(None if x is None or y is None else (y - x) / units for x, y in zip(b, a))
            self.log({"probe": axis, "units": units, "response": self.response[axis]})

    def step_for(self, axis, error, component):
        response = (self.response.get(axis) or (None, None, None))[component]
        if response is None or abs(response) < self.cfg["min_response"][axis]:
            return None
        units = -error / response
        cap = self.cfg["max_step"][axis]
        units = max(-cap, min(cap, units))
        return units if abs(units) >= 0.5 else (0.5 if units > 0 else -0.5)

    def decide(self, box, history):
        tol = self.cfg["tolerance"]
        if not box.get("found"):
            return "abort", None, "box not visible"
        dx, distance, tilt = self.measures(box)
        flapping = len(history) >= 4 and all(h[0] == history[-1][0] for h in history[-4:]) and \
            [h[1] > 0 for h in history[-4:]] in ([True, False] * 2, [False, True] * 2)
        wants = []
        if tilt is not None and abs(tilt) > tol["tilt_deg"]:
            wants.append(("roll", tilt, 2, f"edge tilt off by {tilt:.1f} deg"))
        if abs(dx) > tol["pan_px"]:
            wants.append(("pan", dx, 0, f"box {dx:+.0f} px from the reference"))
        far = (box.get("cut_top") and abs(box["cy"] - self.site["cy"]) > tol["cut_cy_px"]) or \
            (not box.get("cut_top") and abs(distance) > tol["area"])
        if far:
            wants.append(("reach", distance, 1, f"distance error {distance:+.2f}"))
        if not wants:
            return "grasp", f"run {self.site['grasp']} rel", f"aligned: dx {dx:+.0f} px, distance {distance:+.2f}"
        if flapping:
            return "abort", None, f"{history[-1][0]} keeps reversing; stopping instead of oscillating"
        for axis, error, component, reason in wants:
            units = self.step_for(axis, error, component)
            if units is not None:
                return axis, jog(axis, units), reason
        return "abort", None, f"no probed axis moves the view enough for: {wants[0][3]}"

    def run(self):
        self.probe()
        history = []
        for step in range(self.cfg["max_steps"]):
            box = self.observe()
            decision, command, reason = self.decide(box, history)
            entry = {"step": step, "decision": decision, "command": command, "reason": reason,
                     "box": {k: box.get(k) for k in ("cx", "cy", "area", "tilt", "cut_top")}}
            if command is None:
                self.log(entry)
                return {"result": decision, "reason": reason, "steps": step}
            status = self.act(command)
            entry["status"] = {k: status.get(k) for k in ("ok", "error", "holding", "gripper_current_ma")}
            self.log(entry)
            if not status.get("ok"):
                return {"result": "refused", "reason": status.get("error"), "steps": step}
            if decision == "grasp":
                return {"result": "holding" if status.get("holding") else "empty", "steps": step + 1}
            units = float(command.split()[2])
            history.append((decision, units))
        return {"result": "max_steps", "steps": self.cfg["max_steps"]}
