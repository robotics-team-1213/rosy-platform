#!/usr/bin/env python3
"""Safety monitor, guarded command wrapper, failure diagnosis, episode lifecycle, and candidate quality scoring
for `cell_auto_pick.py` (`cell_auto_safety.py`).

Split from `cell_auto_pick.py` (D-766 2) so both the autonomous pick-and-place orchestrator (`cell_auto_pick.py`)
and its safety/failure/episode helpers (`cell_auto_safety.py`) stay compact and single-responsibility (< 415 lines).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_decisions as cd  # noqa: E402
import cell_diagnose  # noqa: E402
from cell_observe import wrap90  # noqa: E402
import cell_params as prm  # noqa: E402
from cell_pick_geom import surface_z  # noqa: E402

TEMP_STOP_C, PWM_FRACTION = prm.default("auto.temp_stop_c"), prm.default("auto.pwm_fraction")


_CAPS_CACHE = {}  # (path, mtime_ns, size) -> caps; every Guarded builds a Monitor, the caps file does not change per pick


def session_caps(config: dict):
    """PWM cap of each follower joint (IDs 11..16 in order) from the record session's caps file, else None."""
    path = (config.get("record") or {}).get("caps")
    try:
        p = Path(path).expanduser()
        key = (str(p), p.stat().st_mtime_ns, p.stat().st_size)
    except (TypeError, OSError):
        return None
    if key not in _CAPS_CACHE:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            caps = [raw[k]["pwm"] for k in sorted(raw, key=int)]
        except (ValueError, KeyError, OSError):
            return None
        if len(_CAPS_CACHE) >= 16:
            _CAPS_CACHE.pop(next(iter(_CAPS_CACHE)))
        _CAPS_CACHE[key] = caps
    return _CAPS_CACHE[key]


class Aborted(Exception):
    pass


class Monitor:
    """Reads the runner's live state before each command; a reason string means stop."""

    def __init__(self, cell, config: dict, clock=time.time):
        s = config.get("safety", {})
        self.cell, self.stale_s, self.clock = cell, s.get("stale_s", 5.0), clock
        self.caps, self.fallback_cap = session_caps(config), s.get("pwm_cap", 300)
        self.params, self.near_since, self.last_pos, self.last = config.get("params"), {}, None, {}
        self.last_pwm = None
        self.temp_c = s.get("temp_stop_c", prm.get(self.params, "auto.temp_stop_c", TEMP_STOP_C))

    def stop(self, reason: str, **why) -> str:
        self.last = {"reason": reason, **why}
        return reason

    def check(self, state: dict | None = None) -> str | None:
        state = self.cell.act("state") if state is None else state
        if not state.get("ok") or state.get("fault"):
            return self.stop(f"runner: {state.get('fault') or state.get('error')}", rule="runner fault")
        if state.get("t") and time.time() - state["t"] > self.stale_s:
            return self.stop(
                "stale live state",
                rule="stale state",
                value=round(time.time() - state["t"], 1),
                limit=self.stale_s,
            )
        health = state.get("health") or {}
        self.last_pwm = list(health.get("pwm") or [])
        if max(health.get("temp_c") or [0]) >= self.temp_c:
            return self.stop(
                f"motor temperature {max(health['temp_c'])} C",
                rule="motor temperature",
                value=max(health["temp_c"]),
                limit=self.temp_c,
            )
        return self.pwm_stall(health.get("pwm") or [], state.get("state"))

    def pwm_stall(self, pwm: list, pos) -> str | None:
        """A joint at its own cap fraction AND not moving for the window is blocked; a moving joint never trips this."""
        frac, window = prm.get(self.params, "auto.pwm_fraction", PWM_FRACTION), prm.get(self.params, "auto.pwm_window_s")
        still, now, last, self.last_pos = (
            prm.get(self.params, "auto.pwm_move_units"),
            self.clock(),
            self.last_pos,
            (list(pos) if pos is not None else None),
        )
        for i, v in enumerate(pwm[:5]):
            cap = self.caps[i] if self.caps and i < len(self.caps) else self.fallback_cap
            moved = pos is not None and last is not None and i < len(pos) and abs(pos[i] - last[i]) >= still
            if abs(v) < frac * cap or moved:
                self.near_since.pop(i, None)
            elif now - self.near_since.setdefault(i, now) >= window:
                return self.stop(
                    f"joint {i + 1} PWM {abs(v)} is {abs(v) / cap:.0%} of its cap {cap} and has not moved for {window} s",
                    rule="pwm stall",
                    joint=i + 1,
                    value=abs(v),
                    cap=cap,
                    fraction=frac,
                    window_s=window,
                )
        return None


class Guarded:
    """A cell whose every motion command is preceded by the safety check; a failed check parks and raises."""

    def __init__(self, cell, config: dict):
        self.cell, self.monitor, self._last_state = cell, Monitor(cell, config), None

    def act(self, command: str) -> dict:
        if command == "state":
            state = self.cell.act("state")
            self._last_state = (self.monitor.clock(), state)
            return state
        words, cached = command.split(), self._last_state
        self._last_state = None
        if (words[3] if words[0] == "checked" else words[0]) not in ("park", "state", "retreat"):
            reason = self.monitor.check(cached[1] if cached and self.monitor.clock() - cached[0] <= 0.1 else None)
            if reason:
                cd.emit(
                    "safety",
                    {**self.monitor.last, "command": command},
                    ["continue", "park and stop"],
                    "park and stop",
                    "rule",
                    reason,
                )
                self.cell.act("park")
                raise Aborted(reason)
        return self.cell.act(command)

    def frame(self, camera: str):
        return self.cell.frame(camera)


def object_sized(mask, params=None):
    """Only object-sized blobs: a whole surface in view (the board, a tray edge) is not what an open finger meets."""
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > prm.get(params, "objects.surface_min_px")]
    if not big:  # nothing to drop: no lookup over the whole frame
        return mask.copy()
    keep_lut = np.ones(n, dtype=bool)
    keep_lut[big] = False
    return np.where(keep_lut[labels], mask, 0).astype(mask.dtype)


def finger_room(mask, roi, pixel_fn, o: dict, closing_deg: float | None = None, params=None) -> dict:
    """Free mm on each closing side and the jaw margin that fits (cell_finger_room); margin None means no room."""
    import cell_finger_room as fr

    return fr.jaw_margin(fr.own_removed(mask, roi, pixel_fn, o), roi, pixel_fn, o, closing_deg, params)


def after_failure(config: dict, site: str, target: dict, moved: dict, wrist_on: bool, failed_yaws: list) -> dict:
    """Diagnose a failed pick from the contact pose and choose the next change from the strategy table."""
    contact = next((s for s in moved["steps"] if s.get("contact") and s.get("state")), None)
    contact_z = None
    if contact is not None:
        from cell_surface import fk_z
        contact_z = round(fk_z(contact["state"], config.get("tcp_x_m")), 4)
    surface = surface_z(config, site)
    diag = cell_diagnose.diagnose(
        moved["result"],
        contact_z,
        surface,
        surface + target["entry"]["top_height_mm"] / 1000,
        target["pick"]["z"],
        config.get("params"),
    )
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


def open_episode(cell, config: dict, source: str, dest: str, object_id: str):
    """A raw training episode around one carry (episode_recorder.py), when config['episodes'] names a root."""
    spec = config.get("episodes")
    if not spec:
        return None
    folder = Path(spec["root"]).expanduser() / f"{time.strftime('%Y%m%d-%H%M%S')}-{source}-to-{dest}"
    folder.mkdir(parents=True, exist_ok=True)
    task = spec.get("tasks", {}).get(f"{source}->{dest}") or f"Pick the green container from the {source} and place it on the {dest}."
    (folder / "task.json").write_text(
        json.dumps(
            {
                "task": task,
                "object": object_id,
                "cameras": spec["cameras"],
                "io": str(config.get("io", "")),
                "payload": config.get("_payload"),
            }
        )
    )
    if not cell.act(f"episode start {folder}").get("ok"):
        return None
    import episode_recorder
    return episode_recorder.CameraSession(folder, spec["cameras"])


def close_episode(cell, episode, keep: bool, why: str = "") -> None:
    """A confirmed carry is saved; any other ending is kept as a labelled failure with why."""
    if episode is not None:
        cell.act("episode save" if keep else f"episode fail {' '.join(why.split()) or 'unconfirmed'}")
        episode.finish()


def score_pick_candidate(cand: dict[str, Any], start_xy: tuple[float, float] = (0.0, 0.0)) -> float:
    """Compute a composite pick candidate quality score combining finger clearance (`jaw_margin_mm`),
    OpenCV structural container confidence (`shape_score`), and proximity to `start_xy`."""
    obj = cand.get("object") or {}
    margin_mm = float(obj.get("jaw_margin_mm") if obj.get("jaw_margin_mm") is not None else 6.0)
    struct = obj.get("structure") or {}
    shape_score = float(struct.get("shape_score", 0.85))
    raw_m = obj.get("raw_m") or [0.0, 0.0]
    dist_m = math.dist((float(raw_m[0]), float(raw_m[1])), (float(start_xy[0]), float(start_xy[1])))
    split_penalty = 0.15 if "split_from" in obj else 0.0
    return round(0.45 * min(1.0, margin_mm / 12.0) + 0.35 * shape_score + 0.20 * max(0.0, 1.0 - dist_m / 0.25) - split_penalty, 4)
