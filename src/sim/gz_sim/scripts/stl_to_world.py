#!/usr/bin/env python3
"""STL 평면도 선화를 Gazebo 벽 박스 월드로 바꾼다. ROS 도 시뮬레이터도 안 띄운다.

입력은 mm 단위 2D 건축 선화다(X-Z 평면에 눕혀진 mesh, Y 두께는 무시한다). 벽은
이중선으로, 곡선(로터리 링, S 커브)은 짧은 선분 사슬로 그려져 있다.

벽과 바닥 표시의 구분은 **묶음 크기**로 한다. 선화를 끝점이 닿는 묶음으로 묶으면 실제
구조는 다섯 개다 — 외곽 프레임, 방, 로터리 링, 로터리 섬, S 커브. 전부 하나가 수백
mm 이어진 큰 묶음이다. 남은 것은 123 mm 짜리 작은 사각형 여덟 개다 — 좌측 통로의
주차 슬롯 넷과 우하단 통로의 사다리 rung 넷(2026-09-22 사용자 결정: 바닥 표시로
생략). 그래서 묶음 범위(extent)가 150 mm 미만이면 표시로 버리고, 하나라도 크면 벽으로
남긴다.

벽 박스 두께는 선 중심 ±12 mm 다. 이중선 간격 ~25 mm 인 두 박스가 겹쳐 한 벽이 되고,
사이에 끼인 틈은 맵에 남지 않는다. 도면 축척은 1:1 — 실험에서 로봇이 약간의 여유로
통과했다.

    python3 stl_to_world.py "260919 MAP FILE.STL" -o ../worlds/rosy_road.world
    python3 world_to_map.py ../worlds/rosy_road.world \
        -o ../../../runtime/navigation/map/rosy_road \
        --resolution 0.02 --seed 0.48,0.64
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

#: 선을 이만큼 두껍게 칠해 벽으로 본다(반폭, mm). 작게 잡으면 도로가 도면 그대로
#: 남고, 이중선 사이의 좁은 틈은 맵 해상도와 inflation 이 흡수한다. 크게(12 mm) 잡으면
#: 도로가 도면보다 양쪽 12 mm 씩 좁아져 통로가 봉쇄된다(실측).
WALL_HALF_MM = 5

#: 묶음 범위가 이 미만이면 바닥 표시다. 실측 — 표시 여덟 묶음은 전부 extent 123 mm,
#: 가장 작은 구조 묶음(로터리 섬)은 474 mm 다. 그 사이에서 고른다.
MARK_MAX_EXTENT_MM = 150.0

#: 뼈대에 붙어 있는 표시(로터리 입구 X자, 통로 십자 표시)는 짧은 선분들만의 공간
#: 묶음으로 잡는다. 30~90 mm 선분끼리 30 mm 안에서 체이닝한 묶음의 범위가 이 미만이고
#: 선분이 넷 이상이면 표시다 — 벽 곡선은 활선이 촘촘히 이어져 한 묶음이 수백 mm 다.
SHORT_MARK_MIN_MM, SHORT_MARK_MAX_MM = 30.0, 90.0
SHORT_MARK_CHAIN_MM, SHORT_MARK_EXTENT_MM, SHORT_MARK_MIN_N = 30.0, 200.0, 4

#: 문 여닫이 안쪽의 사다리 표시는 구조 묶음에 붙어 있어 위 규칙으로 못 잡는다 — 이
#: 도면 한정의 명시적 영역이다. 이 안쪽 선분은 표시로 버려 문(폭 ~293 mm)을 연다.
#: 좌표는 도면 mm, (x0, z0, x1, z1).
MARK_ZONES: list[tuple[float, float, float, float]] = [(695.0, 455.0, 795.0, 835.0)]

#: 두 선분이 같은 사슬의 연장으로 병합되는 최대 꺾임. 곡선은 이 값마다 박스가 끊긴다.
MERGE_ANGLE_DEG = 12.0

#: 벽 높이. rplidar 가 보는 0.125 m 를 상단이 아니라 안쪽으로 감싸야 한다.
WALL_HEIGHT_M = 0.30

Point = tuple[float, float]
Segment = tuple[float, float, float, float]


def parse_stl(path: Path) -> list[Segment]:
    """이진 STL 의 모서리를 (x0, z0, x1, z1) 평면 선분으로 꺼낸다. mm.

    같은 모서리는 두 삼각형에서 방향만 반대로 온다 — 시작점이 사전 순으로 앞인 쪽으로
    통일해 하나로 센다. 길이 0 꼭지 모서리는 버린다.
    """
    data = path.read_bytes()
    if data[:5].lower() == b"solid" and b"facet" in data[:1000]:
        raise SystemExit(f"{path}: ASCII STL 은 아직 받지 않는다")
    count = struct.unpack("<I", data[80:84])[0]
    seen: set[tuple[Point, Point]] = set()
    offset = 84
    for _ in range(count):
        values = struct.unpack("<12fH", data[offset:offset + 50])
        tri = [values[3 + 3 * i:6 + 3 * i] for i in range(3)]
        for i in range(3):
            (ax, _, az), (bx, _, bz) = tri[i], tri[(i + 1) % 3]
            if math.hypot(bx - ax, bz - az) < 0.5:
                continue
            a, b = (round(ax, 1), round(az, 1)), (round(bx, 1), round(bz, 1))
            seen.add((a, b) if a <= b else (b, a))
        offset += 50
    return sorted((*a, *b) for (a, b) in seen)


def snap(point: Point) -> Point:
    """끝점을 스냅 격자에 붙인다. STL 모서리는 두 삼각형에서 미세하게 다르게 기록된다."""
    return (round(point[0] / 2.0), round(point[1] / 2.0))


def components_of(segments: list[Segment]) -> list[list[Segment]]:
    """끝점이 닿는(스냅 격자에서 같은 칸) 선분들을 묶음으로 만든다."""
    by_endpoint: dict[Point, list[int]] = {}
    for i, (ax, az, bx, bz) in enumerate(segments):
        by_endpoint.setdefault(snap((ax, az)), []).append(i)
        by_endpoint.setdefault(snap((bx, bz)), []).append(i)
    out: list[list[Segment]] = []
    visited = [False] * len(segments)
    for start in range(len(segments)):
        if visited[start]:
            continue
        visited[start] = True
        queue, group = deque([start]), []
        while queue:
            i = queue.popleft()
            group.append(segments[i])
            ax, az, bx, bz = segments[i]
            for point in (snap((ax, az)), snap((bx, bz))):
                for j in by_endpoint.get(point, ()):
                    if not visited[j]:
                        visited[j] = True
                        queue.append(j)
        out.append(group)
    return out


def separate_marks(segments: list[Segment]) -> tuple[list[Segment], list[Segment]]:
    """묶음별로 벽/바닥 표시를 가른다. 반환은 (벽, 표시). 규칙은 셋이다.

    1. 묶음 범위가 150 mm 미만 — 이 도면의 슬롯/rung 사각형 여덟 개.
    2. 뼈대에 붙은 짧은 선분들의 공간 묶음(범위 200 mm 미만, 넷 이상) — 로터리 입구
       X자와 통로 십자 표시. 벽 곡선은 활선이 촘촘해 한 묶음이 수백 mm 이어진다.
    3. 명시적 영역(MARK_ZONES) — 문 안쪽 사다리 표시는 구조와 붙어 있어 따로 지정한다.
    """
    marks: list[Segment] = []
    kept: list[Segment] = []
    for cluster in components_of(segments):
        xs = [v for s in cluster for v in (s[0], s[2])]
        zs = [v for s in cluster for v in (s[1], s[3])]
        extent = math.hypot(max(xs) - min(xs), max(zs) - min(zs))
        (marks if extent < MARK_MAX_EXTENT_MM else kept).extend(cluster)

    def mid(seg: Segment) -> Point:
        return ((seg[0] + seg[2]) / 2, (seg[1] + seg[3]) / 2)

    shorts = [s for s in kept
              if SHORT_MARK_MIN_MM <= math.hypot(s[2] - s[0], s[3] - s[1])
              <= SHORT_MARK_MAX_MM]
    used = [False] * len(shorts)
    for i in range(len(shorts)):
        if used[i]:
            continue
        used[i] = True
        queue, group = deque([i]), [i]
        while queue:
            a = queue.popleft()
            for j in range(len(shorts)):
                if not used[j] and math.dist(mid(shorts[a]), mid(shorts[j])) \
                        < SHORT_MARK_CHAIN_MM:
                    used[j] = True
                    queue.append(j)
                    group.append(j)
        xs = [v for k in group for v in (shorts[k][0], shorts[k][2])]
        zs = [v for k in group for v in (shorts[k][1], shorts[k][3])]
        extent = math.hypot(max(xs) - min(xs), max(zs) - min(zs))
        if extent < SHORT_MARK_EXTENT_MM and len(group) >= SHORT_MARK_MIN_N:
            marks.extend(shorts[k] for k in group)
        else:
            kept.extend(shorts[k] for k in group)

    zone_kept: list[Segment] = []
    for seg in kept:
        mx, mz = mid(seg)
        if any(x0 <= mx <= x1 and z0 <= mz <= z1
               for (x0, z0, x1, z1) in MARK_ZONES):
            marks.append(seg)
        else:
            zone_kept.append(seg)
    return zone_kept, marks


def merge_runs(segments: list[Segment]) -> list[list[Point]]:
    """선분들을 끝점이 닿는 사슬로 이어 폴리라인 묶음으로 만든다."""
    used = [False] * len(segments)
    by_endpoint: dict[Point, list[int]] = {}
    for i, (ax, az, bx, bz) in enumerate(segments):
        by_endpoint.setdefault(snap((ax, az)), []).append(i)
        by_endpoint.setdefault(snap((bx, bz)), []).append(i)

    def take(point: Point) -> int | None:
        for j in by_endpoint.get(snap(point), ()):
            if not used[j]:
                return j
        return None

    runs: list[list[Point]] = []
    for i in range(len(segments)):
        if used[i]:
            continue
        used[i] = True
        ax, az, bx, bz = segments[i]
        points = [(ax, az), (bx, bz)]
        for forward in (True, False):  # 사슬을 양쪽 끝으로 늘린다
            while True:
                edge = points[-1] if forward else points[0]
                j = take(edge)
                if j is None:
                    break
                used[j] = True
                jax, jaz, jbx, jbz = segments[j]
                nxt = (jbx, jbz) if snap((jax, jaz)) == snap(edge) else (jax, jaz)
                if forward:
                    points.append(nxt)
                else:
                    points.insert(0, nxt)
        runs.append(points)
    return runs


def runs_to_boxes(runs: list[list[Point]], scale: float
                  ) -> list[tuple[float, float, float, float]]:
    """폴리라인을 꺾임 12° 마다 끊어 벽 박스 (cx, cy, length, yaw) 로 만든다. 단위 m.

    벽 두께는 선 중심 ±WALL_HALF_MM 다. 이중선(간격 ~25 mm)의 두 박스가 겹치지 않는
    사이 틈은 맵 해상도(0.02 m)와 costmap inflation 이 흡수한다 — 쌍을 합치는 시도는
    오정합으로 프레임을 통째로 칠해버렸다(실측).
    """
    boxes: list[tuple[float, float, float, float]] = []
    for points in runs:
        run = [points[0]]
        for point in points[1:]:
            if math.dist(run[-1], point) < 1.0:  # mm — 같은 자리의 점은 건너뛴다
                continue
            run.append(point)
            if len(run) < 3:
                continue
            (ax, az), (mx, mz), (bx, bz) = run[-3], run[-2], run[-1]
            a0 = math.atan2(mz - az, mx - ax)
            a1 = math.atan2(bz - mz, bx - mx)
            turn = abs((a1 - a0 + math.pi) % (2 * math.pi) - math.pi)
            if math.degrees(turn) > MERGE_ANGLE_DEG:
                boxes.append(_box(run[-3], run[-2], scale))
                run = run[-2:]
        boxes.append(_box(run[0], run[-1], scale))
    return boxes


def _box(start: Point, end: Point, scale: float) -> tuple[float, float, float, float]:
    # 이어붙임 여유 +12 mm: 꺾이는 관절의 쐐기 틈을 메우지 않으면 벽이 점선이 되고
    # 자유 면적이 벽을 새 나간다(실측 — map4 에서 방 벽이 점선으로 뚫렸다).
    length = max(math.hypot(end[0] - start[0], end[1] - start[1]) * scale / 1000
                 + 0.012, 0.02)
    return ((start[0] + end[0]) / 2 * scale / 1000,
            (start[1] + end[1]) / 2 * scale / 1000,
            length, math.atan2(end[1] - start[1], end[0] - start[0]))


def write_world(path: Path, boxes: list[tuple[float, float, float, float]]) -> None:
    sdf = ET.Element("sdf", {"version": "1.8"})
    world = ET.SubElement(sdf, "world", {"name": "rosy_road"})
    physics = ET.SubElement(world, "physics", {"name": "1ms", "type": "ignored"})
    ET.SubElement(physics, "max_step_size").text = "0.001"
    ET.SubElement(physics, "real_time_factor").text = "1.0"
    for name, filename in (
        ("Physics", "gz-sim-physics-system"),
        ("UserCommands", "gz-sim-user-commands-system"),
        ("SceneBroadcaster", "gz-sim-scene-broadcaster-system"),
        ("Sensors", "gz-sim-sensors-system"),
        ("Imu", "gz-sim-imu-system"),
    ):
        plugin = ET.SubElement(world, "plugin", {"filename": filename,
                                                 "name": f"gz::sim::systems::{name}"})
        if name == "Sensors":
            ET.SubElement(plugin, "render_engine").text = "ogre2"
    ground = ET.SubElement(world, "model", {"name": "ground_plane"})
    ground_link = ET.SubElement(ground, "link", {"name": "l"})
    for kind in ("visual", "collision"):
        part = ET.SubElement(ground_link, kind, {"name": "v"})
        plane_el = ET.SubElement(ET.SubElement(part, "geometry"), "plane")
        ET.SubElement(plane_el, "normal").text = "0 0 1"
        ET.SubElement(plane_el, "size").text = "4 2"
    walls = ET.SubElement(world, "model", {"name": "walls"})
    ET.SubElement(walls, "static").text = "true"
    for i, (cx, cy, length, yaw) in enumerate(boxes):
        link = ET.SubElement(walls, "link", {"name": f"wall_{i:03d}"})
        pose = ET.SubElement(link, "pose")
        pose.text = f"{cx:.4f} {cy:.4f} {WALL_HEIGHT_M / 2:.3f} 0 0 {yaw:.4f}"
        for kind in ("visual", "collision"):
            part = ET.SubElement(link, kind, {"name": kind[:1]})
            box = ET.SubElement(ET.SubElement(part, "geometry"), "box")
            ET.SubElement(box, "size").text = (
                f"{length:.4f} {WALL_HALF_MM * 2 / 1000:.4f} {WALL_HEIGHT_M:.3f}")
    ET.indent(sdf, space="  ")
    path.write_text('<?xml version="1.0" ?>\n' + ET.tostring(sdf, encoding="unicode"),
                    encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stl_to_world")
    p.add_argument("stl", type=Path)
    p.add_argument("-o", "--out", type=Path, required=True)
    p.add_argument("--scale", type=float, default=1.0,
                   help="도면 mm -> 월드 m 배율. 1.0 은 도면이 실물 크기라는 뜻이다")
    args = p.parse_args(argv)

    segments = parse_stl(args.stl)
    walls, marks = separate_marks(segments)
    print(f"선분 {len(segments)}: 벽 {len(walls)} / 바닥 표시 {len(marks)}")
    boxes = runs_to_boxes(merge_runs(walls), args.scale)
    write_world(args.out, boxes)
    span_x = max(v for s in segments for v in (s[0], s[2])) * args.scale / 1000
    span_z = max(v for s in segments for v in (s[1], s[3])) * args.scale / 1000
    print(f"{args.out}: 벽 박스 {len(boxes)} 개, 사이트 {span_x:.2f} x {span_z:.2f} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
