#!/usr/bin/env python3
"""Run the semantic camera -> policy -> command path without ROS imports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = REPO_ROOT / "src/runtime/control"
if str(CONTROL_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_ROOT))
_PACKAGE_ROOTS = {
    "core": "src/runtime/core",
    "core_common": "src/contracts/core_common",
    "core_events": "src/runtime/core_events",
    "core_features": "src/runtime/core_features",
}
for _package in _PACKAGE_ROOTS:
    _path = str(REPO_ROOT / _PACKAGE_ROOTS[_package])
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control.sensing.perception.road import (  # noqa: E402
    detect_road_observation,
    render_road_preview,
    road_observation_payload,
)
from core.bridge import traffic_gate, translate  # noqa: E402
from core_events.events.bus import EventBus  # noqa: E402
from core_features.line_follow import (  # noqa: E402
    LineFollowConfig,
    LineFollowManager,
    LineFollowMode,
    LineObservation,
)
from core_features.traffic_policy import (  # noqa: E402
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
)


SCENE_PATH = (
    CONTROL_ROOT / "map/map_260905_update_v2/semantic/road_scene.yaml")
WIDTH = 320
HEIGHT = 240


class _SyntheticGround:
    """Known projection used only by the host-rendered camera fixture."""

    def distance(self, row, column=None):
        del column
        return max(0.02, (HEIGHT - float(row)) / 400.0)


class _CommandRecorder:
    def __init__(self):
        self.applied = []

    def set_nav_twist(self, twist, now=None):
        self.applied.append((float(now), twist))


def _camera_frame(*, stop_row=None, crosswalk=False,
                  signal=None) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 35, dtype=np.uint8)
    frame[65:, 156:164] = (235, 235, 235)
    if stop_row is not None:
        frame[stop_row - 3:stop_row + 3, 55:265] = (245, 245, 245)
    if crosswalk:
        for row in (130, 142, 154, 166):
            frame[row - 2:row + 2, 75:245] = (245, 245, 245)
    colours = {
        "RED": (0, 0, 255),
        "YELLOW": (0, 255, 255),
        "GREEN": (0, 255, 0),
    }
    if signal in colours:
        cv2.circle(frame, (42, 29), 10, colours[signal], thickness=-1)
    return frame


def _detector_sample(frame, *, stamp, map_id, scene_revision):
    observation = detect_road_observation(
        frame, ground=_SyntheticGround())
    payload = road_observation_payload(
        "CAMERA_ROAD", stamp, map_id, scene_revision, observation)
    return observation, translate.road_evidence(payload)


def _render_montage(frames: list[tuple[str, np.ndarray]], output: Path) -> None:
    canvas = Image.new("RGB", (WIDTH * len(frames), HEIGHT + 34), "#0b1220")
    draw = ImageDraw.Draw(canvas)
    for index, (label, frame) in enumerate(frames):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        canvas.paste(Image.fromarray(rgb), (index * WIDTH, 34))
        draw.text((index * WIDTH + 10, 10), label, fill="#f3f6fb")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _render_preview_evidence(frames: list[np.ndarray], output_dir: Path) -> None:
    images = [Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
              for frame in frames]
    images[2].save(output_dir / "camera_preview_demo.jpg", quality=86)
    images[0].save(
        output_dir / "camera_preview_simulation.gif",
        save_all=True,
        append_images=images[1:],
        duration=650,
        loop=0,
        optimize=False,
    )


def _svg(scene: dict, samples: list[dict]) -> str:
    width, height = 1120, 650
    map_x, map_y, map_w, map_h = 55, 90, 470, 490
    timeline_x = 585
    all_points = [point for lane in scene["lanes"]
                  for point in lane["centerline"]]
    xs = [float(point[0]) for point in all_points]
    ys = [float(point[1]) for point in all_points]
    min_x, max_x = min(xs) - 0.15, max(xs) + 0.15
    min_y, max_y = min(ys) - 0.15, max(ys) + 0.15

    def point(x, y):
        sx = map_x + (float(x) - min_x) / (max_x - min_x) * map_w
        sy = map_y + map_h - (float(y) - min_y) / (max_y - min_y) * map_h
        return sx, sy

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1220"/>',
        '<text x="55" y="42" fill="#f3f6fb" font-family="sans-serif" '
        'font-size="24" font-weight="700">Semantic road closed-loop simulation</text>',
        f'<text x="55" y="66" fill="#9eacc0" font-family="monospace" '
        f'font-size="13">{scene["map_id"]} · {scene["scene_revision"]} · '
        'camera pixels only → policy → CORE command</text>',
        f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" '
        'rx="12" fill="#172234" stroke="#41506a"/>',
    ]
    for lane in scene["lanes"]:
        points = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in
            (point(*raw) for raw in lane["centerline"]))
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="#f6f7f8" '
            'stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>')
    for crosswalk in scene["crosswalks"]:
        cx, cy = point(*crosswalk["center"])
        for index in range(int(crosswalk["stripe_count"])):
            offset = (index - 2) * 10
            parts.append(
                f'<line x1="{cx + offset}" y1="{cy - 38}" '
                f'x2="{cx + offset}" y2="{cy + 38}" '
                'stroke="#6ee7f2" stroke-width="6"/>')
    for stop in scene["stop_lines"]:
        sx, sy = point(*stop["center"])
        parts.append(
            f'<line x1="{sx}" y1="{sy - 48}" x2="{sx}" y2="{sy + 48}" '
            'stroke="#ff5a67" stroke-width="8"/>')
    for signal in scene["traffic_signals"]:
        sx, sy = point(signal["pose"][0], signal["pose"][1])
        parts.extend([
            f'<circle cx="{sx}" cy="{sy}" r="15" fill="#ff3347"/>',
            f'<text x="{sx + 22}" y="{sy + 5}" fill="#f3f6fb" '
            f'font-family="monospace" font-size="12">{signal["id"]}</text>',
        ])
    parts.extend([
        f'<text x="{timeline_x}" y="104" fill="#f3f6fb" '
        'font-family="sans-serif" font-size="18" font-weight="700">'
        'Perception / policy / command timeline</text>',
        f'<line x1="{timeline_x}" y1="125" x2="1065" y2="125" '
        'stroke="#41506a"/>',
    ])
    state_colours = {
        "FOLLOW": "#35d6a5",
        "APPROACH": "#ffd166",
        "STOP_REQUIRED": "#ff7b72",
        "WAIT_SIGNAL": "#ff5a67",
        "PROCEED": "#42e66c",
        "HOLD": "#d58cff",
    }
    for index, sample in enumerate(samples):
        y = 158 + index * 66
        colour = state_colours[sample["policy_state"]]
        bar = 180 * sample["command_linear"] / 0.08
        parts.extend([
            f'<circle cx="{timeline_x + 8}" cy="{y - 5}" r="7" fill="{colour}"/>',
            f'<text x="{timeline_x + 25}" y="{y}" fill="#f3f6fb" '
            f'font-family="monospace" font-size="14">{sample["t_s"]:4.2f}s  '
            f'{sample["phase"]:14s} {sample["policy_state"]}</text>',
            f'<rect x="{timeline_x + 25}" y="{y + 12}" width="180" height="8" '
            'rx="4" fill="#25344b"/>',
            f'<rect x="{timeline_x + 25}" y="{y + 12}" width="{bar:.1f}" '
            f'height="8" rx="4" fill="{colour}"/>',
            f'<text x="{timeline_x + 220}" y="{y + 21}" fill="#9eacc0" '
            f'font-family="monospace" font-size="12">cmd '
            f'{sample["command_linear"]:.3f} m/s · {sample["policy_reason"]}</text>',
        ])
    parts.extend([
        '<text x="55" y="620" fill="#9eacc0" font-family="sans-serif" '
        'font-size="13">HOST-SIM evidence only · no physical Pinky Pro, camera mount, '
        'or stopping-distance acceptance</text>',
        '</svg>',
    ])
    return "\n".join(parts) + "\n"


def run_simulation(output_dir: Path | str) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    scene = yaml.safe_load(SCENE_PATH.read_text(encoding="utf-8"))
    map_id = str(scene["map_id"])
    scene_revision = str(scene["scene_revision"])
    now = [10.0]
    events = EventBus("rosy_semantic_sim")
    line = LineFollowManager(
        events,
        config=LineFollowConfig(
            cruise_speed=0.08,
            max_linear=0.10,
            steering_gain=0.8,
            max_angular=0.7,
            min_confidence=0.35,
            stale_after_s=0.3,
            lost_after_s=3.0,
        ),
        clock=lambda: now[0],
    )
    line.set_mode(LineFollowMode.CAMERA_LINE)
    traffic = TrafficPolicyManager(
        events,
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id=map_id,
            scene_revision=scene_revision,
            policy_revision="traffic-policy-v1",
            approach_distance_m=0.35,
            stop_distance_m=0.12,
            stop_dwell_s=0.5,
            stale_after_s=0.4,
            min_confidence=0.5,
        ),
        clock=lambda: now[0],
        simulation_signal_control=True,
    )
    command = _CommandRecorder()
    samples = []
    montage = []
    preview_frames = []

    def run_frame(phase, at, frame):
        now[0] = at
        detected, road = _detector_sample(
            frame, stamp=at, map_id=map_id,
            scene_revision=scene_revision)
        assert detected.lane is not None
        line.observe(LineObservation(
            source=LineFollowMode.CAMERA_LINE,
            stamp=at,
            visible=True,
            error=detected.lane.error,
            confidence=detected.lane.confidence,
        ), received_at=at, source_now=at)
        traffic.observe(road, received_at=at, source_now=at)
        traffic_gate.apply_line_candidate(
            line, traffic, command, line.tick(at), at)
        status = traffic.status()
        twist = command.applied[-1][1]
        samples.append({
            "phase": phase,
            "t_s": round(at - 10.0, 2),
            "lane_error": round(detected.lane.error, 4),
            "stop_line_visible": detected.stop_line is not None,
            "stop_line_distance_m": (
                None if detected.stop_line is None
                else round(detected.stop_line.distance_m, 4)),
            "crosswalk_visible": detected.crosswalk is not None,
            "signal_colour": (
                None if detected.signal is None else detected.signal.colour),
            "signal_conflict": detected.signal_conflict,
            "policy_state": status.state,
            "policy_reason": status.reason,
            "command_linear": round(twist.linear, 5),
            "command_angular": round(twist.angular, 5),
        })
        montage.append((phase, frame))
        preview_frames.append(render_road_preview(
            frame, detected, source=f"HOST-{phase}", max_width=WIDTH))

    run_frame("clear", 10.0, _camera_frame())
    run_frame("approach", 10.2, _camera_frame(
        stop_row=140, signal="RED"))
    run_frame("red_stop", 10.4, _camera_frame(
        stop_row=198, crosswalk=True, signal="RED"))
    run_frame("red_dwell", 10.7, _camera_frame(
        stop_row=198, crosswalk=True, signal="RED"))
    run_frame("red_wait", 11.0, _camera_frame(
        stop_row=198, crosswalk=True, signal="RED"))
    traffic.set_simulation_signal("GREEN", actor="semantic_host_sim")
    run_frame("green_proceed", 11.2, _camera_frame(
        stop_row=198, crosswalk=True, signal="GREEN"))

    now[0] = 11.7
    traffic_gate.apply_line_candidate(
        line, traffic, command, line.tick(now[0]), now[0])
    stale_status = traffic.status()
    stale_twist = command.applied[-1][1]
    samples.append({
        "phase": "stale",
        "t_s": 1.7,
        "lane_error": None,
        "stop_line_visible": False,
        "stop_line_distance_m": None,
        "crosswalk_visible": False,
        "signal_colour": None,
        "signal_conflict": False,
        "policy_state": stale_status.state,
        "policy_reason": stale_status.reason,
        "command_linear": round(stale_twist.linear, 5),
        "command_angular": round(stale_twist.angular, 5),
    })

    expected = {
        "clear": ("FOLLOW", True),
        "approach": ("APPROACH", True),
        "red_stop": ("STOP_REQUIRED", False),
        "red_wait": ("WAIT_SIGNAL", False),
        "green_proceed": ("PROCEED", True),
        "stale": ("HOLD", False),
    }
    by_phase = {sample["phase"]: sample for sample in samples}
    passed = all(
        by_phase[phase]["policy_state"] == state
        and ((by_phase[phase]["command_linear"] > 0.0) is moving)
        for phase, (state, moving) in expected.items()
    )
    summary = {
        "status": (
            "SEMANTIC_ROAD_HOST_SIM_PASS"
            if passed else "SEMANTIC_ROAD_HOST_SIM_FAIL"),
        "simulation": "synthetic_camera_closed_loop",
        "map_id": map_id,
        "scene_revision": scene_revision,
        "semantic_scene_path": str(SCENE_PATH.relative_to(REPO_ROOT)),
        "semantic_features": {
            key: len(scene[key])
            for key in ("lanes", "crosswalks", "stop_lines",
                        "traffic_signals")
        },
        "semantic_truth_fed_to_detector": False,
        "physical_device_validated": False,
        "samples": samples,
    }
    (target / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (target / "semantic_road_simulation.svg").write_text(
        _svg(scene, samples), encoding="utf-8")
    _render_montage(montage, target / "camera_detection_montage.png")
    _render_preview_evidence(preview_frames, target)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run_simulation(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(
        0 if summary["status"] == "SEMANTIC_ROAD_HOST_SIM_PASS" else 1)


if __name__ == "__main__":
    main()
