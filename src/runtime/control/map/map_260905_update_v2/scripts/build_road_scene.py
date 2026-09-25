#!/usr/bin/env python3
"""Generate the semantic-road Gazebo world and a human review preview."""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

import yaml
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = ROOT / "semantic" / "road_scene.yaml"
DEFAULT_WORLD = ROOT / "worlds" / "map_260905_traffic.world"
DEFAULT_PREVIEW = ROOT / "review" / "map_260905_traffic.png"


def canonical_text_bytes(path: Path) -> bytes:
    """Hash text identically across LF and CRLF worktrees."""
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def validate_scene(scene: dict) -> None:
    """Validate the semantic scene before it can produce runtime assets."""
    groups = ("lanes", "crosswalks", "stop_lines", "traffic_signals")
    seen = set()
    for group in groups:
        for item in scene[group]:
            feature_id = item["id"]
            if feature_id in seen:
                raise ValueError(f"duplicate semantic feature id: {feature_id}")
            seen.add(feature_id)
    stop_line_ids = {item["id"] for item in scene["stop_lines"]}
    lane_ids = {item["id"] for item in scene["lanes"]}
    for signal in scene["traffic_signals"]:
        if signal["controlled_stop_line_id"] not in stop_line_ids:
            raise ValueError("traffic signal references unknown stop line")
        if signal["controlled_lane_id"] not in lane_ids:
            raise ValueError("traffic signal references unknown lane")


def _material(name: str, active: bool = True) -> str:
    colors = {
        "white": "1 1 1 1",
        "red": "1 0.02 0.02 1" if active else "0.12 0.01 0.01 1",
        "yellow": "1 0.7 0.02 1" if active else "0.12 0.08 0.01 1",
        "green": "0.02 1 0.08 1" if active else "0.01 0.12 0.02 1",
        "dark": "0.04 0.04 0.04 1",
        "pole": "0.18 0.18 0.18 1",
    }
    color = colors[name]
    return (
        "<material>"
        f"<ambient>{color}</ambient><diffuse>{color}</diffuse>"
        f"<emissive>{color if name in {'red', 'yellow', 'green'} else '0 0 0 1'}</emissive>"
        "</material>"
    )


def _box_visual(name: str, x: float, y: float, z: float, sx: float, sy: float,
                sz: float, yaw: float, material: str) -> str:
    return (
        f'<visual name="{name}"><pose>{x:.6f} {y:.6f} {z:.6f} 0 0 {yaw:.9f}</pose>'
        f"<geometry><box><size>{sx:.6f} {sy:.6f} {sz:.6f}</size></box></geometry>"
        f"{_material(material)}</visual>"
    )


def _segment_visuals(lane: dict) -> list[str]:
    points = lane["centerline"]
    visuals = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        visuals.append(_box_visual(
            f'{lane["id"]}_segment_{index:02d}',
            (float(start[0]) + float(end[0])) / 2.0,
            (float(start[1]) + float(end[1])) / 2.0,
            0.0015, length, float(lane["width_m"]), 0.001,
            math.atan2(dy, dx), "white",
        ))
    return visuals


def _crosswalk_visuals(crosswalk: dict) -> list[str]:
    count = int(crosswalk["stripe_count"])
    travel = float(crosswalk["travel_length_m"])
    stripe = float(crosswalk["stripe_width_m"])
    cx, cy = map(float, crosswalk["center"])
    heading = float(crosswalk["heading_rad"])
    visuals = []
    for index in range(count):
        offset = -travel / 2.0 + (index + 0.5) * travel / count
        x = cx + math.cos(heading) * offset
        y = cy + math.sin(heading) * offset
        visuals.append(_box_visual(
            f'{crosswalk["id"]}_stripe_{index:02d}', x, y, 0.0016,
            stripe, float(crosswalk["crossing_width_m"]), 0.001,
            heading, "white",
        ))
    return visuals


def _stop_line_visual(stop_line: dict) -> str:
    x, y = map(float, stop_line["center"])
    heading = float(stop_line["heading_rad"])
    return _box_visual(
        stop_line["id"], x, y, 0.0017,
        float(stop_line["width_m"]), float(stop_line["length_m"]), 0.001,
        heading, "white",
    )


def _traffic_signal_model(signal: dict) -> str:
    x, y, z, roll, pitch, yaw = map(float, signal["pose"])
    active = str(signal["default_state"]).upper()
    sid = signal["id"]
    lamp_z = {"red": 0.255, "yellow": 0.215, "green": 0.175}
    lamps = []
    for color, height in lamp_z.items():
        lamps.append(
            f'<visual name="{sid}_{color}"><pose>0 -0.018 {height:.3f} 1.570796327 0 0</pose>'
            "<geometry><sphere><radius>0.012</radius></sphere></geometry>"
            f'{_material(color, active == color.upper())}</visual>'
        )
    return (
        f'<model name="{sid}"><static>true</static>'
        f'<pose>{x:.6f} {y:.6f} {z:.6f} {roll:.6f} {pitch:.6f} {yaw:.9f}</pose>'
        '<link name="link">'
        '<collision name="pole_collision"><pose>0 0 0.125 0 0 0</pose>'
        '<geometry><cylinder><radius>0.008</radius><length>0.25</length></cylinder></geometry></collision>'
        '<visual name="pole"><pose>0 0 0.125 0 0 0</pose>'
        '<geometry><cylinder><radius>0.008</radius><length>0.25</length></cylinder></geometry>'
        f'{_material("pole")}</visual>'
        '<collision name="housing_collision"><pose>0 0 0.215 0 0 0</pose>'
        '<geometry><box><size>0.045 0.030 0.125</size></box></geometry></collision>'
        '<visual name="housing"><pose>0 0 0.215 0 0 0</pose>'
        '<geometry><box><size>0.045 0.030 0.125</size></box></geometry>'
        f'{_material("dark")}</visual>'
        f'{"".join(lamps)}</link></model>'
    )


def build_model(scene: dict) -> str:
    visuals = []
    for lane in scene["lanes"]:
        visuals.extend(_segment_visuals(lane))
    for crosswalk in scene["crosswalks"]:
        visuals.extend(_crosswalk_visuals(crosswalk))
    visuals.extend(_stop_line_visual(item) for item in scene["stop_lines"])
    signals = "".join(_traffic_signal_model(item) for item in scene["traffic_signals"])
    return (
        '\n    <!-- GENERATED from semantic/road_scene.yaml; markings are visual-only. -->\n'
        '    <model name="semantic_road_markings"><static>true</static><link name="link">'
        + "".join(visuals) + "</link></model>" + signals + "\n"
    )


def _world_to_pixel(point: tuple[float, float], height: int,
                    origin=(-1.5, -0.75), resolution=0.005) -> tuple[int, int]:
    x, y = point
    return (round((x - origin[0]) / resolution),
            height - 1 - round((y - origin[1]) / resolution))


def render_preview(scene: dict, output: Path) -> None:
    image = Image.open(ROOT / "maps" / "map_260905_occupancy.png").convert("RGB")
    draw = ImageDraw.Draw(image)
    for lane in scene["lanes"]:
        points = [_world_to_pixel(tuple(map(float, point)), image.height)
                  for point in lane["centerline"]]
        draw.line(points, fill=(20, 120, 255), width=3, joint="curve")
    for crosswalk in scene["crosswalks"]:
        cx, cy = map(float, crosswalk["center"])
        count = int(crosswalk["stripe_count"])
        travel = float(crosswalk["travel_length_m"])
        width = float(crosswalk["crossing_width_m"])
        for index in range(count):
            x = cx - travel / 2.0 + (index + 0.5) * travel / count
            p0 = _world_to_pixel((x - 0.007, cy - width / 2.0), image.height)
            p1 = _world_to_pixel((x + 0.007, cy + width / 2.0), image.height)
            draw.rectangle((p0[0], p1[1], p1[0], p0[1]), fill=(80, 220, 240))
    for stop_line in scene["stop_lines"]:
        x, y = map(float, stop_line["center"])
        half = float(stop_line["length_m"]) / 2.0
        draw.line([_world_to_pixel((x, y - half), image.height),
                   _world_to_pixel((x, y + half), image.height)],
                  fill=(255, 40, 40), width=4)
    for signal in scene["traffic_signals"]:
        x, y = map(float, signal["pose"][:2])
        px, py = _world_to_pixel((x, y), image.height)
        color = {"RED": (255, 30, 30), "YELLOW": (255, 200, 20),
                 "GREEN": (20, 220, 70)}[signal["default_state"]]
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=color, outline=(0, 0, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def build(scene_path: Path, world_output: Path, preview_output: Path) -> None:
    scene_bytes = canonical_text_bytes(scene_path)
    scene = yaml.safe_load(scene_bytes.decode("utf-8"))
    validate_scene(scene)
    source = ROOT / scene["source_world"]
    digest = hashlib.sha256(canonical_text_bytes(source)).hexdigest()
    if digest != scene["source_world_sha256"]:
        raise ValueError("source world checksum does not match semantic map")
    text = source.read_text(encoding="utf-8")
    marker = "  </world>"
    if marker not in text:
        raise ValueError("source world has no closing world element")
    provenance = (
        "\n    <!-- "
        f"source_world_sha256={digest} "
        f"road_scene_sha256={hashlib.sha256(scene_bytes).hexdigest()}"
        " -->\n"
    )
    generated = text.replace(marker, provenance + build_model(scene) + marker, 1)
    world_output.parent.mkdir(parents=True, exist_ok=True)
    world_output.write_text(generated, encoding="utf-8", newline="\n")
    render_preview(scene, preview_output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--world-output", type=Path, default=DEFAULT_WORLD)
    parser.add_argument("--preview-output", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()
    build(args.scene, args.world_output, args.preview_output)


if __name__ == "__main__":
    main()
