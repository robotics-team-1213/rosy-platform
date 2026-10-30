#!/usr/bin/env python3
"""Autonomous pick and place of catalogue objects for arm S, no human hands (2026-10-28).

observe -> choose -> self-calibrate -> grasp -> place -> verify -> record, each a function:

  observe          top frame, catalogue objects in arm mm through the site's map (cell_objects).
  choose           matched, not tangled, inside the view, plannable (approach 40 mm above the grasp, else 20 mm);
                   a piece split from a merged blob only with a finger-width gap on both closing sides.
  self_calibrate   the map's bias near the object: reuse a saved region, else a pivot circle at a clear point
                   (cell_pivot.pivot_calibrate) saved next to the map; located points are corrected by it.
  grasp candidates the jaws' closing direction is hidden from the top camera: `gripper.closing_axis_offset_deg`
                   (90 = closes along tool y = yaw + 90, theory; 0 = alternative) compete in cell_choices by
                   real outcome (held by jaw position and current = success; soft contact or empty = failure);
                   after a contact or an empty grasp the arm retreats and one more try uses the better record.
                   A square (1-cell) object is orientation-free and does not compete.
  place, verify    transfer places at the destination; the object is looked for there (bias-corrected) when
                   a map and a region are known, else the arm's own placement is trusted once the grasp held.
  record           one cell_attempts row per attempt: outcome, failed stage, the candidate, the bias used.

Safety: no start unless chunk_runner answers; abort (park, then stop) on a runner fault, a motor at 55 C, PWM
at 80 % of the cap twice in a row, or a stale live state. The arm is never left extended.

  cell_auto_pick.py --config cell-pipeline.json --catalog object-catalog.json --roi 40 210 300 400 \\
      --dest belt|x,y [--from pinky] [--dry-run]       # dry-run observes, chooses and plans, prints JSON
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_objects  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402
import cell_place_fit  # noqa: E402
import cell_site_track  # noqa: E402
import cell_diagnose  # noqa: E402
import cell_hooks  # noqa: E402
import cell_wrist_ref  # noqa: E402
from cell_calibrate import learn_bias, self_calibrate  # noqa: E402,F401  (calibration lives there)
import cell_pipeline as cp  # noqa: E402
from cell_observe import keep, predicted_pixel, wrap90  # noqa: E402

CLOSING = "gripper.closing_axis_offset_deg"
TEMP_STOP_C, PWM_FRACTION = prm.default("auto.temp_stop_c"), prm.default("auto.pwm_fraction")


def session_caps(config: dict):
    """PWM cap of each follower joint (IDs 11..16 in order) from the record session's caps file, else None. The
    caps differ per joint (shoulder_lift and elbow_flex 600, the rest 300): one cap for all called a 54 % load
    114 % and aborted a good lift (2026-10-28)."""
    path = (config.get("record") or {}).get("caps")
    try:
        raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return [raw[k]["pwm"] for k in sorted(raw, key=int)]
    except (TypeError, OSError, ValueError, KeyError):
        return None


class Aborted(Exception):
    pass


class Monitor:
    """Reads the runner's live state before each command; a reason string means stop."""

    def __init__(self, cell, config: dict, clock=time.time):
        s = config.get("safety", {})
        self.cell, self.stale_s, self.clock = cell, s.get("stale_s", 5.0), clock
        self.caps, self.fallback_cap = session_caps(config), s.get("pwm_cap", 300)
        self.params, self.near_since, self.last_pos, self.last = config.get("params"), {}, None, {}
        self.last_pwm = None  # PWM of the last check, kept for the transport-stop decision row
        self.temp_c = s.get("temp_stop_c", prm.get(self.params, "auto.temp_stop_c", TEMP_STOP_C))

    def stop(self, reason: str, **why) -> str:
        self.last = {"reason": reason, **why}  # the rule, joint and values the safety decision row keeps
        return reason

    def check(self) -> str | None:
        state = self.cell.act("state")
        if not state.get("ok") or state.get("fault"):
            return self.stop(f"runner: {state.get('fault') or state.get('error')}", rule="runner fault")
        if state.get("t") and time.time() - state["t"] > self.stale_s:
            return self.stop("stale live state", rule="stale state", value=round(time.time() - state["t"], 1), limit=self.stale_s)
        health = state.get("health") or {}
        self.last_pwm = list(health.get("pwm") or [])
        if max(health.get("temp_c") or [0]) >= self.temp_c:
            return self.stop(f"motor temperature {max(health['temp_c'])} C", rule="motor temperature",
                             value=max(health["temp_c"]), limit=self.temp_c)
        return self.pwm_stall(health.get("pwm") or [], state.get("state"))

    def pwm_stall(self, pwm: list, pos) -> str | None:
        """A joint at its own cap fraction AND not moving for the window is blocked; at the cap alone is normal
        while lifting (the elbow saturates leaving home), so a moving joint never trips this."""
        frac, window = prm.get(self.params, "auto.pwm_fraction", PWM_FRACTION), prm.get(self.params, "auto.pwm_window_s")
        still, now, last, self.last_pos = prm.get(self.params, "auto.pwm_move_units"), self.clock(), self.last_pos,             (list(pos) if pos is not None else None)
        # the gripper squeezes at its cap while holding a box, still by design (2026-10-28 floor->belt run aborted
        # at home on 300/300); its load is the grasp verdict's and the temperature watch's, not a stall
        for i, v in enumerate(pwm[:5]):
            cap = self.caps[i] if self.caps and i < len(self.caps) else self.fallback_cap
            moved = pos is not None and last is not None and i < len(pos) and abs(pos[i] - last[i]) >= still
            if abs(v) < frac * cap or moved:
                self.near_since.pop(i, None)
            elif now - self.near_since.setdefault(i, now) >= window:
                return self.stop(f"joint {i + 1} PWM {abs(v)} is {abs(v) / cap:.0%} of its cap {cap} and has not moved for {window} s",
                                 rule="pwm stall", joint=i + 1, value=abs(v), cap=cap, fraction=frac, window_s=window)
        return None


class Guarded:
    """A cell whose every motion command is preceded by the safety check; a failed check parks and raises."""

    def __init__(self, cell, config: dict):
        self.cell, self.monitor = cell, Monitor(cell, config)

    def act(self, command: str) -> dict:
        words = command.split()
        if (words[3] if words[0] == "checked" else words[0]) not in ("park", "state", "retreat"):  # Gate's form
            reason = self.monitor.check()
            if reason:
                cd.emit("safety", {**self.monitor.last, "command": command}, ["continue", "park and stop"], "park and stop", "rule", reason)
                self.cell.act("park")
                raise Aborted(reason)
        return self.cell.act(command)

    def frame(self, camera: str):
        return self.cell.frame(camera)


def surface_z(config: dict, site: str) -> float:
    """The site's surface height (m), which every auto-pick site must state: the grasp height is computed from
    it (catalogue top height - grasp depth), never taken from the site's `z`, which is the taught cube grasp
    height. A site giving only its surface as `z` (a floor at 0.006) was once planned at the surface itself."""
    s = config["sites"][site]
    if "surface_z" not in s:
        raise SystemExit(f"site {site!r}: auto pick needs `surface_z` (the surface height in metres)")
    depth = prm.get(config.get("params"), "auto.grasp_depth_m", 0.015)
    if "z" in s and s["z"] < s["surface_z"] + depth - 1e-9:
        raise SystemExit(f"site {site!r}: z {s['z']} is below surface_z {s['surface_z']} + grasp depth {depth}")
    return s["surface_z"]


def parse_dest(config: dict, source: str, dest: str):
    """A site name, or 'x,y' metres on the source surface -> (site, (x, y))."""
    if dest in config["sites"]:
        return dest, tuple(config["sites"][dest]["place"])
    x, y = (float(v) for v in dest.split(","))
    return source, (x, y)


def observe(cell, config: dict, calibration: dict, site: str, roi, catalog: list):
    import cv2

    record = cell_pivot.map_record(calibration, site)
    if record is None:
        return None, None, [], f"no map for {site}"
    img = cell.frame("top")
    cd.see(keep(f"auto-{site}-top", img))
    poly, lab = config["sites"][site].get("surface_px"), config["sites"][site].get("surface_lab")
    objects = cell_objects.detect(img, roi, record, config["cameras"]["top"], catalog, surface_z(config, site),
                                  config.get("params"), poly, lab, (config.get("objects") or {}).get("hsv"))
    for o in objects:
        o["raw_m"] = [o["centre_mm"][0] / 1000, o["centre_mm"][1] / 1000]
    # the finger-side mask is not clipped to the site polygon: a container on the next surface (the board beside the
    # floor) still meets an open finger (2026-10-29: the jaws came down on a 2-cell on the board, contact at z 0.040)
    near = cell_objects.foreground(img, roi, params=config.get("params"), surface_lab=lab)
    for poly in config["sites"][site].get("markings_px", []):  # flat floor markings (a white line) are no obstacle
        cv2.fillPoly(near, [np.asarray(poly, np.int32) - [roi[0], roi[1]]], 0)
    return img, object_sized(near, config.get("params")), objects, None


def object_sized(mask, params=None):
    """Only object-sized blobs: a whole surface in view (the board, a tray edge) is not what an open finger meets."""
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > prm.get(params, "objects.surface_min_px")]
    out = mask.copy()
    for i in big:
        out[labels == i] = 0
    return out


def finger_room(mask, roi, pixel_fn, o: dict, closing_deg: float | None = None, params=None) -> dict:
    """Free mm on each closing side and the jaw margin that fits (cell_finger_room); margin None means no room."""
    import cell_finger_room as fr

    return fr.jaw_margin(fr.own_removed(mask, roi, pixel_fn, o), roi, pixel_fn, o, closing_deg, params)


def grasp_yaw(config: dict, site: str, o: dict, entry: dict, offset) -> float:
    """Tool yaw (deg) for a closing-axis candidate. The jaws close along tool y = yaw + offset, and must close
    across the object (long axis + jaw_axis_deg_from_long); yaw and yaw + 180 are the same grasp, the one
    nearest the site's own yaw is taken. A square object is only squared up to the site yaw."""
    base = config["sites"][site]["yaw_deg"]
    if offset is None:
        return round(base + max(-10.0, min(10.0, wrap90(o["long_axis_deg"] - base))), 1)
    yaw = o["long_axis_deg"] + entry["grasp"].get("jaw_axis_deg_from_long", 90) - offset
    return round(base + (yaw - base + 90) % 180 - 90, 1)


def jaw_open_for(width_mm: float, params=None, margin_mm: float | None = None) -> float:
    """The jaw value whose finger gap is the object width plus a margin each side. Measured 2026-10-29 from the wrist
    view: about 10.4 mm of gap per unit, 30 mm held at 52.3. Opening to 62 put the fingers ~40 mm out, onto the 2-cells
    standing next to the box; 56 put a finger on the board edge."""
    g = lambda name: prm.get(params, name)  # noqa: E731
    margin = g("auto.jaw_margin_mm") if margin_mm is None else margin_mm  # less where a neighbour is near (finger_room)
    value = g("gripper.held_30mm") + (width_mm + 2 * margin - 30.0) / g("gripper.gap_mm_per_unit")
    return round(min(max(value, g("gripper.held_30mm") + 0.5), g("gripper.open_max")), 2)


def reachable_ends(o: dict, entry: dict, params=None) -> list:
    """Grasp points shifted along a long box's axis, toward the arm's base first: grasp.end_frac of the way from
    the middle to where the jaws would reach the box's end. A square box has none."""
    reach = prm.get(params, "grasp.end_frac") * (entry["length_mm"] - entry["width_mm"]) / 2000
    if reach <= 0:
        return []
    u = math.radians(o["long_axis_deg"])
    ends = [dict(o, raw_m=[o["raw_m"][0] + k * reach * math.cos(u), o["raw_m"][1] + k * reach * math.sin(u)],
                 grasp_shift_mm=round(1000 * k * reach, 1)) for k in (1, -1)]
    return sorted(ends, key=lambda e: math.hypot(*e["raw_m"]))


def plan_pick(config: dict, site: str, dest_site: str, place_xy, o: dict, entry: dict, offset, bias_mm, work: Path,
              yaw: float | None = None, place_yaw: float | None = None):
    """Library for one candidate: grasp 15 mm below the top, approach 40 mm above it (else 20), the yaw and its
    180 degree twin tried in turn. Returns (library path, pick, place, approach_m, yaw) or an error string."""
    height = entry["top_height_mm"] / 1000 - prm.get(config.get("params"), "auto.grasp_depth_m", 0.015)
    x, y = (o["raw_m"][0] - bias_mm[0] / 1000, o["raw_m"][1] - bias_mm[1] / 1000)
    yaw0, error = (grasp_yaw(config, site, o, entry, offset) if yaw is None else yaw), "no plan"
    for approach in (config["plan"]["approach_m"], prm.get(config.get("params"), "auto.approach_near_m", 0.020)):
        for yaw in (yaw0, yaw0 + 180.0, yaw0 - 180.0):
            pick = {"x": round(x, 4), "y": round(y, 4), "z": round(surface_z(config, site) + height, 4), "yaw_deg": yaw}
            s = config["sites"][dest_site]
            place = {"x": place_xy[0], "y": place_xy[1],
                     "z": round(surface_z(config, dest_site) + height + s.get("place_dz", 0.0), 4),
                     "yaw_deg": s["yaw_deg"] if place_yaw is None else place_yaw}
            try:
                jaws = jaw_open_for(entry["width_mm"], config.get("params"), o.get("jaw_margin_mm"))
                # one file per object: two boxes on the floor planned into one name, and the arm went to the other one
                # (2026-10-29, the second candidate overwrote the first's library)
                lib = cp.write_library(dict(config, plan=dict(config["plan"], approach_m=approach, grip_open=jaws)), pick,
                                       place, work / f"auto-{site}-{offset}-{round(1000 * o['raw_m'][0])}_{round(1000 * o['raw_m'][1])}.json")
                return lib, pick, place, approach, yaw, {"approach_m": approach, "grip_open": jaws}
            except SystemExit as exc:
                error = str(exc)[:160]
    return error


def after_failure(config: dict, site: str, target: dict, moved: dict, wrist_on: bool, failed_yaws: list) -> dict:
    """Diagnose a failed pick from the contact pose and choose the next change from the strategy table; the choice is
    a decision row (cell_diagnose). 'other_axis' marks the yaw as failed so the next choice turns 90 degrees."""
    contact = next((s for s in moved["steps"] if s.get("contact") and s.get("state")), None)
    contact_z = None
    if contact is not None:
        from cell_surface import fk_z
        contact_z = round(fk_z(contact["state"]), 4)
    surface = surface_z(config, site)
    diag = cell_diagnose.diagnose(moved["result"], contact_z, surface, surface + target["entry"]["top_height_mm"] / 1000,
                                  target["pick"]["z"], config.get("params"))
    can = {"observe_again"} | ({"wrist_align"} if wrist_on else set())
    square = abs(target["entry"]["length_mm"] - target["entry"]["width_mm"]) < 1e-6
    if square and not any(abs(wrap90(target["pick"]["yaw_deg"] + 90 - f)) <= 5.0 for f in failed_yaws):
        can.add("other_axis")
    actions = cell_diagnose.next_actions(diag["cause"], can)
    chosen = actions[0]
    if chosen in ("other_axis", "observe_again", "wrist_align"):
        failed_yaws.append(target["pick"]["yaw_deg"])
    cd.emit("failure", diag["facts"], actions, chosen, "rule", f"cause {diag['cause']}")
    return {"cause": diag["cause"], "facts": diag["facts"], "options": actions, "chosen": chosen}


def square_entry(entries: dict, o: dict) -> bool:
    e = entries.get(o.get("object"))
    return bool(e) and abs(e["length_mm"] - e["width_mm"]) < 1e-6


def choose(cell, config, calibration, site, dest_site, place_xy, roi, objects, mask, catalog, bias_data, choices, work,
           failed_yaws=(), dest_view=None):
    """Ordered usable targets: [{object, plan...}], and why the others were refused."""
    entries, usable, refused = {e["id"]: e for e in catalog}, [], []
    pixel_fn = lambda p: predicted_pixel(config, calibration, site, p)  # noqa: E731
    p = config.get("params")
    for o in sorted(objects, key=lambda o: ("split_from" in o, math.dist(o["raw_m"], config["sites"][site]["start"]))):
        why = None
        px = pixel_fn(o["raw_m"])
        if o.get("tangled"):
            why = "tangled blob"
        elif not o["matched"]:
            why = "no catalogue match"
        elif px is None or not (roi[0] + 12 <= px[0] <= roi[2] - 12 and roi[1] + 12 <= px[1] <= roi[3] - 12):
            why = "not inside the camera view"
        elif not square_entry(entries, o):
            room = finger_room(mask, roi, pixel_fn, o, None, p)
            if room["margin_mm"] is None:
                why = f"no finger room: {room['free_mm'][0]} / {room['free_mm'][1]} mm free beside it"
        if why:
            refused.append({"centre_mm": o["centre_mm"], "object": o.get("object"), "why": why})
            continue
        entry = entries[o["object"]]
        square = abs(entry["length_mm"] - entry["width_mm"]) < 1e-6
        if not square:
            choices.offer(CLOSING, prm.get(p, "auto.closing_theory_deg"), "theory: closes along tool y = yaw + 90")
            choices.offer(CLOSING, prm.get(p, "auto.closing_alt_deg"), "alternative: closes along tool x")
        offset = None if square else choices.best(CLOSING)
        yaw = None
        if square:  # a square closes either way: take the yaw whose finger sides are clear, else refuse
            closing = prm.get(p, "auto.closing_theory_deg")
            base_yaw = grasp_yaw(config, site, o, entry, None)
            # a yaw that already failed on this object (contact or empty) is not tried again: the next attempt changes it
            fresh = [y for y in (base_yaw, base_yaw + 90.0)
                     if all(abs(wrap90(y - f)) > 5.0 for f in failed_yaws)] or [base_yaw, base_yaw + 90.0]
            rooms = [(y, finger_room(mask, roi, pixel_fn, o, y + closing, p)) for y in fresh]
            yaw, room = next(((y, r) for y, r in rooms if r["margin_mm"] is not None), (None, rooms[0][1]))
            if yaw is None:
                refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": "no finger gap on either closing axis"})
                continue
        region = cell_pivot.bias_at(bias_data, site, o["raw_m"], params=p)
        bias = region["bias_mm"] if region else [0.0, 0.0]
        # the whole footprint, turned the way the jaws hold it, must fit the destination (cell_place_fit)
        held_axis = o["long_axis_deg"] - (yaw if yaw is not None else grasp_yaw(config, site, o, entry, offset))
        places, why = cell_place_fit.options(config, dest_site, place_xy, held_axis, entry,
                                             lambda q: predicted_pixel(config, calibration, dest_site, q), *(dest_view or (None, None)))
        if why:
            refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": f"place: {why}"})
            continue
        o, planned = dict(o, jaw_margin_mm=room["margin_mm"], free_mm=room["free_mm"]), "no place"  # jaws open as far as fits
        for xy, place_yaw in places:
            planned = plan_pick(config, site, dest_site, xy, o, entry, offset, bias, work, yaw, place_yaw)
            for end in (reachable_ends(o, entry, p) if isinstance(planned, str) and "UNREACHABLE" in planned else []):
                # a long box whose middle is out of reach is held nearer its end (2026-10-29: a 2-cell on the moved Pinky)
                planned = plan_pick(config, site, dest_site, xy, end, entry, offset, bias, work, yaw, place_yaw)
                if not isinstance(planned, str):
                    o = end
                    break
            if not isinstance(planned, str):
                break
        if isinstance(planned, str):
            refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": f"planner: {planned}"})
            continue
        usable.append({"object": o, "entry": entry, "offset": offset, "bias_region": region, "bias_mm": bias,
                       "library": planned[0], "pick": planned[1], "place": planned[2], "approach_m": planned[3],
                       "plan": planned[5]})
    return usable, refused


def verify_placed(cell, config, calibration, dest_site, place_xy, roi, catalog, bias_data, object_id, held):
    record = cell_pivot.map_record(calibration, dest_site)
    if roi is None or record is None:
        return {"found": held, "inside": held, "basis": "arm placement"}
    _, _, objects, _ = observe(cell, config, calibration, dest_site, roi, catalog)
    region = cell_pivot.bias_at(bias_data, dest_site, place_xy, params=config.get("params"))
    bx, by = (region["bias_mm"] if region else (0.0, 0.0))
    near = [(1000 * math.dist((o["raw_m"][0] - bx / 1000, o["raw_m"][1] - by / 1000), place_xy), o) for o in objects
            if o.get("object") == object_id]
    if not near:
        return {"found": False, "inside": False, "basis": "map"}
    off, o = min(near, key=lambda pair: pair[0])
    seen = [round(1000 * (o["raw_m"][0] - place_xy[0]), 1), round(1000 * (o["raw_m"][1] - place_xy[1]), 1)]
    return {"found": True, "inside": off <= config.get("verify_tol_mm", 10.0), "off_mm": round(off, 1), "basis": "map",
            "seen_bias_mm": seen, "used_bias_mm": [bx, by]}


from cell_transfer import FOLDED, STILL_HOLDING_UNITS, Gate, transfer_folded  # noqa: E402,F401 - moved there; names kept


def open_episode(cell, config: dict, source: str, dest: str, object_id: str):
    """A raw training episode around one carry (episode_recorder.py), when config["episodes"] names a root."""
    spec = config.get("episodes")
    if not spec:
        return None
    folder = Path(spec["root"]).expanduser() / f"{time.strftime('%Y%m%d-%H%M%S')}-{source}-to-{dest}"
    folder.mkdir(parents=True, exist_ok=True)
    task = spec.get("tasks", {}).get(f"{source}->{dest}") or f"Pick the green container from the {source} and place it on the {dest}."
    (folder / "task.json").write_text(json.dumps({"task": task, "object": object_id, "cameras": spec["cameras"]}))
    if not cell.act(f"episode start {folder}").get("ok"):
        return None
    import episode_recorder
    return episode_recorder.CameraSession(folder, spec["cameras"])  # frames here, never in the arm runner


def close_episode(cell, episode, keep: bool, why: str = "") -> None:
    """A confirmed carry is saved; any other ending is kept as a labelled failure with why (learning needs both)."""
    if episode is not None:
        cell.act("episode save" if keep else f"episode fail {' '.join(why.split()) or 'unconfirmed'}")
        episode.finish()


def run_auto(cell, config, calibration, calibration_path, catalog, roi, source, dest, work: Path, choices,
             dry_run=False, sleep=time.sleep, log=print, attempts=None) -> dict:
    """One object from `source` to `dest`; up to `attempts` grasps (the second with the better candidate)."""
    work, out = Path(work), {"from": source, "to": dest, "attempts": []}
    for site in {source, dest} & {k for k, v in config["sites"].items() if v.get("track")}:  # a robot that moves
        config, out[f"track_{site}"] = cell_site_track.follow(config, site, cell.frame("top"),
                                                              lambda q, s=site: predicted_pixel(config, calibration, s, q), work)
        if not out[f"track_{site}"]["tracked"]:
            return {**out, "result": f"refused: {site}: {out[f'track_{site}'].get('why')}"}
        roi = config["sites"][site]["auto_roi"] if site == source else roi
    dest_site, place_xy = parse_dest(config, source, dest)
    droi = config["sites"][dest_site].get("auto_roi") or (roi if dest_site == source else None)
    guarded = None if dry_run else Guarded(cell, config)
    if guarded is not None and not cell.act("state").get("ok"):
        return {"result": "refused", "error": "start record_session.py --chunks first: no chunk_runner answers"}
    bias_data = cell_pivot.load_bias(cell_pivot.bias_path(calibration_path))
    episode, failed_yaws, dest_view = None, [], None
    if droi is not None and dest_site != source:  # what is already on the destination (cell_place_fit)
        _, dmask, _, derr = observe(cell, config, calibration, dest_site, droi, catalog)
        dest_view = None if derr else (dmask, droi)
    attempts = int(prm.get(config.get("params"), "auto.attempts")) if attempts is None else attempts
    try:
        for attempt in range(attempts):
            t0, tried = time.time(), {"locate": {"found": False}}
            img, mask, objects, error = observe(cell, config, calibration, source, roi, catalog)
            usable, refused = choose(cell, config, calibration, source, dest_site, place_xy, roi, objects, mask, catalog,
                                     bias_data, choices, work, failed_yaws, dest_view) if not error else ([], [])
            cd.target(objects, usable, refused)
            if usable and config.get("decision_model"):  # the model orders what the measurement kept, or vetoes all
                import cell_pick_judge
                import judge_seat

                judged = cell_pick_judge.ask(judge_seat.ollama(**config["decision_model"]), img, usable)
                cd.emit("target_judge", {"candidates": len(usable)}, list(range(len(usable))) + [-1], judged["choice"],
                        judged["by"], judged["reason"])
                usable = [usable[i] for i in judged["order"]]
            row = {"observed": len(objects), "refused": refused}
            out["attempts"].append(row)
            if error or not usable:
                row["error"] = error or "no usable object"
                tried["fail"] = {"stage": "choose", "class": row["error"]}
                if not dry_run:
                    cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"stopped: {row['error']}"}
            target = usable[0]
            known = cell_pivot.bias_at(bias_data, source, target["object"]["raw_m"], params=config.get("params"))
            # a pivot moves the arm outside any reviewed carry: supervised commissioning only (D-911)
            pivot_cell = guarded if not dry_run and "_commissioning" in config else None
            bias_data, problem = self_calibrate(pivot_cell, config, calibration, calibration_path, source,
                                                target["object"]["raw_m"], objects, work, bias_data, sleep, log)
            cd.bias(known, problem, target["object"]["raw_m"])
            if problem and not dry_run:
                tried["locate"] = {"found": True, "arm_m": target["object"]["raw_m"]}
                tried["fail"] = {"stage": "calibrate", "class": problem}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"stopped: {problem}"}
            if not dry_run and problem is None and cell_pivot.bias_at(bias_data, source, target["object"]["raw_m"],
                                                                      params=config.get("params")) \
                    != target["bias_region"]:  # a new region just measured: plan again with it
                usable, refused = choose(cell, config, calibration, source, dest_site, place_xy, roi, objects, mask, catalog,
                                         bias_data, choices, work, failed_yaws, dest_view)
                if not usable:
                    row["error"] = "no usable object after the pivot"
                    return {**out, "result": "stopped: " + row["error"]}
                target = usable[0]
                cd.target(objects, usable, refused)
            o = target["object"]
            tried["locate"] = {"found": True, "arm_m": [target["pick"]["x"], target["pick"]["y"]], "raw_m": o["raw_m"],
                               "object": o["object"], "long_axis_deg": o["long_axis_deg"]}
            tried["grasp_yaw"] = {"choice": target["offset"], "yaw_deg": target["pick"]["yaw_deg"]}
            tried["plan"] = {"pick": target["pick"], "place": target["place"]}
            tried["auto"] = {"object": o["object"], "closing_axis_offset_deg": target["offset"], "bias_mm": target["bias_mm"],
                             "bias_region": target["bias_region"], "approach_m": target["approach_m"]}
            cd.closing(target["offset"], choices.data["values"].get(CLOSING, []), o["object"])
            row.update(chosen=tried["auto"], plan=tried["plan"], pivot_needed=problem, long_axis_deg=o["long_axis_deg"])
            if dry_run:
                return {**out, "result": "planned"}
            folded = prm.get(config.get("params"), "auto.fold_before_transport")
            sequence = FOLDED if folded else cp.SEQUENCE
            episode = open_episode(cell, config, source, dest, o["object"])
            # a hover re-plan keeps the pick's own plan values (jaw opening, approach): the default 62 opening came back
            # through the reach re-plan and the fingers met the board again (2026-10-29)
            same = dict(config, plan=dict(config["plan"], **target.get("plan", {})))
            gate = Gate(guarded, config, calibration, sequence=sequence)
            held = gate.open(target["library"], lambda a: cell_attempts.begin(config, a))
            if held is not None:  # D-911: not a reviewed task (or no supervised trial): nothing moved
                tried["envelope"] = held
                tried["transfer"] = {"result": "held", "at": "preflight", "steps": [], "envelope": held}
                close_episode(cell, episode, False, f"held: {held['reason']}")
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {held['reason']}"}
            wrist, capture, pinch, feel = cell_hooks.pick_hooks(same, gate, target, cp.write_library, source, dest_site, cd.emit, calibration)
            moved = transfer_folded(gate, target["library"], wrist=wrist, after_place=capture,
                                    pinch=pinch, feel=feel, sequence=sequence)
            tried["envelope"] = gate.assessment
            tried["wrist"] = (moved.get("wrist") or next((s for s in moved["steps"] if s.get("command") == "wrist"), None)
                              or ("disabled or uncalibrated" if wrist is None else None))
            tried["transfer"] = moved
            if moved["result"] == "empty" or (moved["result"] == "contact" and moved.get("at") in ("run descend_pick", "run grasp_pick")):
                decided = after_failure(config, source, target, moved, wrist is not None, failed_yaws)
                tried["diagnosis"] = decided
                if decided["chosen"] in ("ask_person", "probe_surface"):
                    close_episode(cell, episode, False, f"{decided['cause']}: {decided['chosen']}")
                    episode = None
                    cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                    return {**out, "result": f"stopped: {decided['cause']} -> {decided['chosen']}"}
            held = moved["result"] == "placed" or any(s.get("holding") for s in moved["steps"])
            if target["offset"] is not None and moved["result"] in ("placed", "empty", "contact"):
                choices.outcome(CLOSING, target["offset"], held, f"{moved['result']} at yaw {target['pick']['yaw_deg']}")
                choices.save()
            if moved["result"] == "placed":
                place_xy = (target["place"]["x"], target["place"]["y"])  # where it was put (cell_place_fit may move it)
                tried["verify"] = verify_placed(guarded, config, calibration, dest_site, place_xy, droi, catalog,
                                                bias_data, o["object"], held)
                cd.emit("verify", dict(tried["verify"]), [True, False], tried["verify"]["inside"], "measurement",
                        f"placement seen on the {tried['verify']['basis']}")
                tried["learned_bias"] = learn_bias(config, calibration_path, dest_site, place_xy, tried["verify"])
                pending = cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site).with_suffix(".pending.json")
                if pending.exists():  # the wrist reference counts only for a place the top camera confirmed
                    if tried["verify"].get("inside"):
                        pending.replace(cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site))
                    else:
                        pending.unlink()
            # only a carry the camera confirmed becomes training data
            close_episode(cell, episode, moved["result"] == "placed" and tried["verify"]["inside"],
                          f"{moved['result']} at {moved.get('at')}" if moved["result"] != "placed" else "placed but not seen at the destination")
            episode = None
            cd.after(moved, choices.best(CLOSING), attempt + 1 < attempts, guarded.monitor)
            cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
            if moved["result"] == "placed" and tried["verify"]["inside"]:
                return {**out, "result": "placed"}
            grasped = any(s.get("command") == "run grasp_pick" and s.get("holding") for s in moved["steps"])
            if moved["result"] == "contact" and grasped:  # stopped while carrying: the box is in the jaws, not on
                return {**out, "result": f"stopped: holding after a stop at {moved['at']}"}  # the surface to re-observe
            if moved["result"] not in ("empty", "contact"):  # a fault, a refusal or a misplaced object: a person looks
                if moved["result"] in ("fault", "refused"):
                    cell.act("park")
                return {**out, "result": f"stopped: {moved['result']}"}
    except Aborted as stop:
        close_episode(cell, episode, False, f"aborted: {stop}")
        return {**out, "result": f"aborted: {stop}"}
    except Exception:  # never stop with the arm extended
        if guarded is not None:
            cell.act("park")
        close_episode(cell, episode, False, "pipeline exception")
        raise
    return {**out, "result": f"stopped: {attempts} attempts"}


def load_config(path: Path) -> dict:
    import cell_perception

    config = json.loads(path.read_text())
    config["profiles"] = {camera: cell_perception.load_profile(Path(spec.get("profile_path", config["profile_path"])).expanduser())
                          for camera, spec in config["cameras"].items()}
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    config["params"] = prm.load(config.get("params_path"))["values"]  # cell-params.example.json form
    return config


def main(argv=None):
    import cell_choices

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--dest", required=True, help="a site name from the config, or x,y metres on the source surface")
    ap.add_argument("--from", dest="source", default="pinky")
    ap.add_argument("--dry-run", action="store_true", help="observe, choose and plan only; print JSON")
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of this one carry (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    config = load_config(args.config)
    if args.commissioning:
        config["_commissioning"] = {"person_at_switch": True}
    work = Path(config["work_dir"]).expanduser()
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    calibration_path = Path(config["calibration_path"]).expanduser()
    cp.KEEP["dir"] = work / "frames"
    cell_attempts.start(work / "attempts.jsonl", knowledge=config.get("knowledge"), params=config.get("params_path"),
                        arm_id=config.get("arm_id", "arm_s"))
    if not args.dry_run:
        cd.start(work / "decisions.jsonl", knowledge=config.get("knowledge"))
    import cell_preflight

    dark = [f"{name}: {why}" for name, ok, why in cell_preflight.lights({c: cell.frame(c) for c in config["cameras"]},
                                                                         config.get("params")) if not ok]
    if dark:  # nothing is seen in the dark: no observe, no motion
        print(json.dumps({"from": args.source, "to": args.dest, "result": "refused", "error": "; ".join(dark)}, indent=1))
        return 1
    result = run_auto(cell, config, cal.load(calibration_path), calibration_path, cell_objects.load_catalog(args.catalog),
                      args.roi, args.source, args.dest, work, cell_choices.Choices(work / "choices.json"), args.dry_run)
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"] in ("placed", "planned") else 1


if __name__ == "__main__":
    sys.exit(main())
