"""D-472 LED identity: which one anonymous blob shows the requested on/off/on blink.

Pure: frames in, a verdict out. ``sample_frame`` measures, per blob, the share of pixels
in a ring around it whose HSV colour is the requested lamp colour (hue band, saturation
and brightness floors). ``decide`` links the blobs of consecutive frames by nearest
pixel distance, turns each chain's shares into on/off/unsure, and looks for the rosy-face
pattern: on (<= max_on_s), off for [min_off_s, max_off_s], on again (<= max_on_s).

``matched`` only when exactly one chain shows it, every frame of the window is there
(no gap over max_gap_s, ends included), the newest frame is fresh and one calibration
revision covers the window.

D-596 3 (camera at 2-3 fps): the measured off time is the gap between the last "on" frame
before and the first after, so it is always longer than the lamp's 1 s off; min_off_s 0.8 s
still refuses a one-frame flicker (two frame intervals at 3 fps is 0.67 s) and max_off_s 2.2 s
and max_gap_s 1.1 s let one dropped frame through at 2 fps. Steady colour: when the blink is not
decoded but the window holds exactly one anonymous blob in every frame and it turns the colour
on (an off frame, then at least ``steady_min_on`` on frames in a row), that blob matches with
``evidence.mode = "steady"`` (a quick tag for a single anonymous robot). Anything else is ``ambiguous`` with a reason: ``none``,
``multiple``, ``frames_missing``, ``stale``, ``calibration_changed``. A chain that loses
its blob (occlusion, merge) ends there and cannot match across the hole.

All thresholds are provisional (D-472 implementation 1: measure on ceiling_north first).
No robot id is known here; Fleet binds the verdict to the robot it asked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import cv2
import numpy as np

PROCESSOR_REVISION = "led-identity/4"
#: D-472 4: Fleet's window is at most 6 s; a little slack for clock rounding.
MAX_WINDOW_S = 6.5
#: Frames kept per challenge (6 s at 10 fps); a faster camera stops sampling, then reads as frames missing.
MAX_SAMPLES = 64

#: OpenCV hue (0..179) bands for the lamp_pattern identify colours. Blue stays clear of the
#: navigating cyan (~90) and the robots' teal shell; amber is rgb(DIM, DIM/3, 0), ~10.
DEFAULT_HUES: Mapping[str, tuple[int, int]] = {"blue": (105, 135), "amber": (4, 22)}


@dataclass(frozen=True)
class LedConfig:
    hues: Mapping[str, tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_HUES))
    # led-identity/3 (site ceiling_north 2026-10-10 11:23, rosy_40 asked blue): the lamp lights the
    # floor beside the robot, its glow centred ~1.8 blob radii out and mostly S 60-110 / V 120-150.
    # The /2 values (S>=110, V>=150, ring to 1.6 r) read ring shares 0.0005 on / 0.0 off: "none".
    # These read 0.039 on / 0.003 off on the same frames.
    min_saturation: int = 60
    min_value: int = 120
    ring_inner: float = 0.6       # x blob radius
    ring_outer: float = 2.6       # x blob radius
    on_fraction: float = 0.02     # lit share of the ring at or above: on
    off_fraction: float = 0.005   # at or below: off; between: unsure
    min_off_s: float = 0.8
    max_off_s: float = 2.2
    max_on_s: float = 1.7
    max_gap_s: float = 1.1        # a longer hole between frames (or at a window end): frames missing
    steady_min_on: int = 2        # D-596 3: on frames in a row for a steady-colour match
    max_step_px: float = 60.0     # blob link distance between consecutive frames
    stale_s: float = 1.5          # newest frame older than this at decision time: stale


@dataclass(frozen=True)
class Blob:
    x_px: float
    y_px: float
    radius_px: float
    map_x: float
    map_y: float


@dataclass(frozen=True)
class Sample:
    captured_at: float
    calibration_revision: str | None
    blobs: tuple[Blob, ...]
    lit: tuple[float, ...]  # ring share per blob, same order


def sample_frame(image: np.ndarray, *, captured_at: float, calibration_revision: str | None,
                 blobs: Sequence[Blob], color: str, config: LedConfig = LedConfig()) -> Sample:
    low, high = config.hues[color]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lit_mask = (hue >= low) & (hue <= high) & (sat >= config.min_saturation) & (val >= config.min_value)
    height, width = lit_mask.shape
    rows, cols = np.ogrid[:height, :width]
    shares = []
    for blob in blobs:
        distance = np.hypot(cols - blob.x_px, rows - blob.y_px)
        ring = (distance >= config.ring_inner * blob.radius_px) & (distance <= config.ring_outer * blob.radius_px)
        count = int(ring.sum())
        shares.append(0.0 if count == 0 else float(lit_mask[ring].sum()) / count)
    return Sample(captured_at, calibration_revision, tuple(blobs), tuple(shares))


def decide(samples: Sequence[Sample], *, not_before: float, not_after: float, now: float,
           config: LedConfig = LedConfig()) -> dict:
    window = sorted((s for s in samples if not_before <= s.captured_at <= not_after),
                    key=lambda s: s.captured_at)
    evidence: dict = {"frames": len(window), "max_gap_s": None, "candidates": []}
    if not window:
        return _ambiguous("frames_missing", evidence)
    times = [not_before] + [s.captured_at for s in window] + [min(now, not_after)]
    evidence["max_gap_s"] = round(max(b - a for a, b in zip(times, times[1:])), 3)
    if len({s.calibration_revision for s in window}) != 1:
        return _ambiguous("calibration_changed", evidence)
    if now - window[-1].captured_at > config.stale_s:
        return _ambiguous("stale", evidence)
    if evidence["max_gap_s"] > config.max_gap_s:
        return _ambiguous("frames_missing", evidence)
    matches = []
    chains = _chains(window, config.max_step_px)
    for chain in chains:
        found = _blink(chain, config)
        if found is not None:
            matches.append((chain, found))
            evidence["candidates"].append(found)
    if not matches:
        for chain in chains:
            if len(chain) != len(window):
                continue
            found = _steady(chain, config, require_off_after=True)
            if found is not None:
                matches.append((chain, found))
                evidence["mode"] = "steady"
                evidence["off_on_off"] = True
                evidence["candidates"].append(found)
    if not matches and len(chains) == 1 and all(len(s.blobs) == 1 for s in window):
        found = _steady(chains[0], config)
        if found is not None:
            matches.append((chains[0], found))
            evidence["mode"] = "steady"
            evidence["candidates"].append(found)
    if len(matches) != 1:
        return _ambiguous("none" if not matches else "multiple", evidence)
    chain, found = matches[0]
    t, blob, _share = chain[-1]
    return {"state": "matched", "reason": None, "x": blob.map_x, "y": blob.map_y,
            "captured_at": t, "calibration_revision": window[0].calibration_revision,
            "evidence": evidence}


def _ambiguous(reason: str, evidence: dict) -> dict:
    return {"state": "ambiguous", "reason": reason, "x": None, "y": None, "captured_at": None,
            "calibration_revision": None, "evidence": evidence}


def _chains(window: Sequence[Sample], max_step_px: float) -> list[list[tuple[float, Blob, float]]]:
    """Greedy nearest links frame to frame; an unlinked blob starts a chain, an unlinked chain ends."""
    done: list[list] = []
    open_: list[list] = [[(window[0].captured_at, b, s)] for b, s in zip(window[0].blobs, window[0].lit)]
    for sample in window[1:]:
        pairs = sorted((math.hypot(b.x_px - c[-1][1].x_px, b.y_px - c[-1][1].y_px), ci, bi)
                       for ci, c in enumerate(open_) for bi, b in enumerate(sample.blobs))
        linked_c: dict[int, int] = {}
        linked_b: set[int] = set()
        for distance, ci, bi in pairs:
            if distance <= max_step_px and ci not in linked_c and bi not in linked_b:
                linked_c[ci] = bi
                linked_b.add(bi)
        next_open = []
        for ci, chain in enumerate(open_):
            if ci in linked_c:
                bi = linked_c[ci]
                chain.append((sample.captured_at, sample.blobs[bi], sample.lit[bi]))
                next_open.append(chain)
            else:
                done.append(chain)  # lost: occluded, merged or left the view
        next_open.extend([(sample.captured_at, b, s)] for bi, (b, s) in
                         enumerate(zip(sample.blobs, sample.lit)) if bi not in linked_b)
        open_ = next_open
    return done + open_


def _blink(chain, config: LedConfig) -> dict | None:
    """The on/off/on evidence of one chain, or None."""
    states = [(t, "on" if s >= config.on_fraction else "off" if s <= config.off_fraction else "?", s)
              for t, _b, s in chain]
    ons = [i for i, (_t, st, _s) in enumerate(states) if st == "on"]
    for a, b in zip(ons, ons[1:]):
        between = [st for _t, st, _s in states[a + 1:b]]
        if "off" not in between:
            continue
        first_start = a
        while first_start - 1 >= 0 and states[first_start - 1][1] == "on":
            first_start -= 1
        second_end = b
        while second_end + 1 < len(states) and states[second_end + 1][1] == "on":
            second_end += 1
        off_s = states[b][0] - states[a][0]
        on1_s = states[a][0] - states[first_start][0]
        on2_s = states[second_end][0] - states[b][0]
        if (config.min_off_s <= off_s <= config.max_off_s
                and on1_s <= config.max_on_s and on2_s <= config.max_on_s):
            on_share = min(s for _t, st, s in states if st == "on")
            off_share = max(s for _t, st, s in states[a + 1:b] if st == "off")
            return {"off_s": round(off_s, 3), "on1_s": round(on1_s, 3), "on2_s": round(on2_s, 3),
                    "min_on_share": round(on_share, 4), "max_off_share": round(off_share, 4),
                    "frames": len(chain)}
    return None


def _steady(chain, config: LedConfig, *, require_off_after: bool = False) -> dict | None:
    """D-596 3: an off frame, then ``steady_min_on`` on frames in a row; None otherwise."""
    run, seen_off, found, on_at = 0, False, None, None
    for t, _b, share in chain:
        if share <= config.off_fraction:
            if found is not None:
                return found
            seen_off, run = True, 0
        elif share >= config.on_fraction and seen_off:
            if run == 0:
                on_at = t
            run += 1
            if run >= config.steady_min_on and (not require_off_after or t - on_at >= 1.0):
                found = {"on_at": round(t, 3), "on_frames": run, "frames": len(chain)}
                if not require_off_after:
                    return found
        else:
            run, found = 0, None
    return None
