#!/usr/bin/env python3
"""Run deterministic closed-loop IR/camera line-follow host simulations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (
    REPO_ROOT / "src/core/control",
    REPO_ROOT / "src/contracts/core_common",
    REPO_ROOT / "src/core/core_events",
    REPO_ROOT / "src/core/core_features",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from control.sensing.perception.lane import IRLineCalibration, detect_ir_line, detect_lane_error
from core_events.events.bus import EventBus
from core_features.line_follow import (
    LineFollowConfig,
    LineFollowManager,
    LineFollowMode,
    LineObservation,
)


DT_S = 0.1
STEPS = 100
LANE_HALF_WIDTH_M = 0.06
LOOKAHEAD_M = 0.08


def _ir_detection(error: float):
    calibration = IRLineCalibration(
        black=(100.0, 100.0, 100.0), white=(900.0, 900.0, 900.0))
    strengths = [math.exp(-((position - error) / 0.70) ** 2)
                 for position in (-1.0, 0.0, 1.0)]
    raw = [100.0 + 800.0 * strength for strength in strengths]
    return detect_ir_line(raw, calibration)


def _camera_detection(error: float):
    width, height = 160, 120
    centre = int(round(width * 0.5 * (1.0 + error)))
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, max(0, centre - 6):min(width, centre + 6)] = 255
    return detect_lane_error(
        frame, bright_threshold=180, roi_top_fraction=0.4,
        washed_fraction=0.4, min_pixels=80)


def _run_mode(mode: LineFollowMode) -> tuple[dict, list[dict]]:
    now = [10.0]
    events = EventBus("rosy_sim")
    manager = LineFollowManager(
        events,
        config=LineFollowConfig(
            cruise_speed=0.09, max_linear=0.10, steering_gain=0.8,
            max_angular=0.7, min_confidence=0.35,
            stale_after_s=0.3, lost_after_s=3.0),
        clock=lambda: now[0],
    )
    manager.set_mode(mode)
    x_m, cross_track_m, yaw_rad = 0.0, 0.035, 0.12
    initial_cross_track_m = cross_track_m
    samples = []

    for step in range(STEPS):
        ideal_error = max(-0.95, min(
            0.95, (cross_track_m + LOOKAHEAD_M * math.sin(yaw_rad))
            / LANE_HALF_WIDTH_M))
        detected = (_ir_detection(ideal_error) if mode is LineFollowMode.IR_LINE
                    else _camera_detection(ideal_error))
        assert detected is not None
        manager.observe(LineObservation(
            source=mode, stamp=now[0], visible=True,
            error=detected.error, confidence=detected.confidence,
        ), received_at=now[0], source_now=now[0])
        decision = manager.tick(now[0])

        # Differential-drive planar kinematics close the loop: controller
        # output changes pose, and the next detector input comes from that pose.
        x_m += decision.linear * math.cos(yaw_rad) * DT_S
        cross_track_m += decision.linear * math.sin(yaw_rad) * DT_S
        yaw_rad += decision.angular * DT_S
        samples.append({
            "step": step,
            "t": round(step * DT_S, 2),
            "x_m": round(x_m, 5),
            "cross_track_m": round(cross_track_m, 5),
            "yaw_rad": round(yaw_rad, 5),
            "error": round(detected.error, 4),
            "confidence": round(detected.confidence, 4),
            "linear": round(decision.linear, 5),
            "angular": round(decision.angular, 5),
            "state": manager.status().state,
        })
        now[0] += DT_S

    tracking_speeds = [item["linear"] for item in samples if item["linear"] > 0.0]
    straight = min(samples, key=lambda item: abs(item["error"]))
    now[0] += 0.31
    stale = manager.tick(now[0])
    now[0] += 3.01
    lost = manager.tick(now[0])
    final_cross_track_m = samples[-1]["cross_track_m"]
    result = {
        "closed_loop": True,
        "tracking_samples": len(tracking_speeds),
        "initial_cross_track_m": initial_cross_track_m,
        "final_cross_track_m": final_cross_track_m,
        "final_yaw_rad": samples[-1]["yaw_rad"],
        "converged": abs(final_cross_track_m) <= 0.01,
        "straight_speed": straight["linear"],
        "minimum_tracking_speed": min(tracking_speeds),
        "maximum_angular": max(abs(item["angular"]) for item in samples),
        "stale_stop": stale.linear == 0.0 and stale.angular == 0.0,
        "loss_latched": manager.status().state == "LOST" and lost.linear == 0.0,
        "final_reason": manager.status().reason,
        "lane_lost_events": sum(
            event.type == "nav.lane_lost" for event in events.history()),
    }
    return result, samples


def _svg(series: dict[str, list[dict]]) -> str:
    width, height = 920, 460
    plot_x, plot_y, plot_w, plot_h = 70, 55, 800, 310
    colours = {"IR_LINE": "#30d5c8", "CAMERA_LINE": "#ffbf69"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1220"/>',
        '<text x="70" y="30" fill="#f3f6fb" font-family="sans-serif" font-size="20">D-143 closed-loop line-follow host simulation</text>',
        f'<line x1="{plot_x}" y1="{plot_y + plot_h / 2}" x2="{plot_x + plot_w}" y2="{plot_y + plot_h / 2}" stroke="#617086" stroke-dasharray="6 5"/>',
        f'<line x1="{plot_x}" y1="{plot_y}" x2="{plot_x}" y2="{plot_y + plot_h}" stroke="#617086"/>',
        '<text x="12" y="70" fill="#9eacc0" font-family="sans-serif" font-size="12">+6 cm</text>',
        '<text x="18" y="218" fill="#9eacc0" font-family="sans-serif" font-size="12">lane</text>',
        '<text x="12" y="366" fill="#9eacc0" font-family="sans-serif" font-size="12">-6 cm</text>',
    ]
    for mode, samples in series.items():
        points = []
        for index, sample in enumerate(samples):
            x = plot_x + index * plot_w / max(1, len(samples) - 1)
            y = plot_y + plot_h * (0.5 - sample["cross_track_m"] / 0.12)
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{colours[mode]}" stroke-width="4"/>')
    for index, mode in enumerate(("IR_LINE", "CAMERA_LINE")):
        x = 80 + index * 260
        parts.extend([
            f'<line x1="{x}" y1="410" x2="{x + 34}" y2="410" stroke="{colours[mode]}" stroke-width="4"/>',
            f'<text x="{x + 44}" y="415" fill="#f3f6fb" font-family="sans-serif" font-size="14">{mode}</text>',
        ])
    parts.append('<text x="555" y="415" fill="#9eacc0" font-family="sans-serif" font-size="13">controller output feeds next robot pose</text>')
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def run_simulation(output_dir: Path | str) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    modes = {}
    series = {}
    for mode in (LineFollowMode.IR_LINE, LineFollowMode.CAMERA_LINE):
        result, samples = _run_mode(mode)
        modes[mode.value] = result
        series[mode.value] = samples
    passed = all(result["converged"] and result["stale_stop"]
                 and result["loss_latched"] for result in modes.values())
    summary = {
        "status": "HOST_SIMULATION_PASS" if passed else "HOST_SIMULATION_FAIL",
        "simulation": "closed_loop_unicycle_kinematics",
        "physical_device_validated": False,
        "modes": modes,
        "series": series,
    }
    (target / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (target / "line_follow_simulation.svg").write_text(_svg(series), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_simulation(args.output)
    print(json.dumps(summary["modes"], indent=2, sort_keys=True))
    raise SystemExit(0 if summary["status"] == "HOST_SIMULATION_PASS" else 1)


if __name__ == "__main__":
    main()
