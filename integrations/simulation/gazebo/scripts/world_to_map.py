#!/usr/bin/env python3
"""월드 기하에서 nav2 점유 격자를 바로 만든다. 시뮬레이터도 ROS 도 띄우지 않는다.

왜 필요한가: 항법을 시험하려면 맵이 있어야 하는데, 맵을 SLAM 으로 뜨려면 로봇이 먼저
그 월드를 돌 수 있어야 한다. 좁은 통로 월드에서는 그 순서가 막힌다 — 맵이 없으니 nav2
를 못 쓰고, nav2 없이 몰면 벽에 끼여 odom 이 폭주하고, 그 odom 으로 뜬 맵은 쓸 수 없다.
여기서 만드는 것은 **정답 맵**이다. 항법 시험의 입력으로 쓰라고 있는 것이지, SLAM 결과를
대신한다고 주장하는 물건이 아니다. 매핑 품질을 재려면 SLAM 맵과 이것을 비교하면 된다.

박스 충돌체만 읽는다. mesh 를 쓰는 모델(`model://shelf` 등)은 담기지 않으므로,
그런 월드는 SLAM 맵을 쓴다.

    python3 world_to_map.py rosy_maze.world -o maps/rosy_maze --seed 0,0
"""

from __future__ import annotations

import argparse
import math
import sys
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

#: rplidar_link 의 바닥 기준 높이. 이보다 위/아래로만 뻗은 구조물은 스캔에 잡히지 않으므로
#: 맵에도 넣지 않는다 — 넣으면 로봇이 보지 못하는 벽을 플래너만 아는 상태가 된다.
LIDAR_Z = 0.125

FREE, OCCUPIED, UNKNOWN = 0, 100, -1


def _floats(text: str | None, count: int) -> list[float]:
    values = [float(v) for v in (text or "").split()] if text else []
    return (values + [0.0] * count)[:count]


class Box:
    """월드 좌표에 놓인 축 회전 직육면체 (yaw 만 쓴다)."""

    def __init__(self, cx: float, cy: float, cz: float, yaw: float,
                 sx: float, sy: float, sz: float) -> None:
        self.cx, self.cy, self.cz, self.yaw = cx, cy, cz, yaw
        self.sx, self.sy, self.sz = sx, sy, sz

    def spans_lidar(self, z: float = LIDAR_Z) -> bool:
        return self.cz - self.sz / 2 <= z <= self.cz + self.sz / 2

    def contains(self, x: float, y: float) -> bool:
        dx, dy = x - self.cx, y - self.cy
        cos, sin = math.cos(-self.yaw), math.sin(-self.yaw)
        lx, ly = dx * cos - dy * sin, dx * sin + dy * cos
        return abs(lx) <= self.sx / 2 and abs(ly) <= self.sy / 2

    def bounds(self) -> tuple[float, float, float, float]:
        """회전한 직사각형의 실제 AABB. 대각선 반경으로 잡으면 6 m 짜리 얇은 벽 하나가
        캔버스를 12 m 로 부풀리고, 맵의 절반이 빈 unknown 이 된다."""
        cos, sin = abs(math.cos(self.yaw)), abs(math.sin(self.yaw))
        half_x = self.sx / 2 * cos + self.sy / 2 * sin
        half_y = self.sx / 2 * sin + self.sy / 2 * cos
        return self.cx - half_x, self.cy - half_y, self.cx + half_x, self.cy + half_y


def read_boxes(path: Path) -> list[Box]:
    root = ET.parse(path).getroot()
    world = root.find("world")
    if world is None:
        raise SystemExit(f"{path}: no <world>")
    boxes: list[Box] = []
    for model in world.iter("model"):
        mx, my, mz, _mr, _mp, myaw = _floats(model.findtext("pose"), 6)
        for link in model.iter("link"):
            lx, ly, lz, _lr, _lp, lyaw = _floats(link.findtext("pose"), 6)
            for collision in link.iter("collision"):
                size = collision.find("./geometry/box/size")
                if size is None:
                    continue
                cx, cy, cz, _cr, _cp, cyaw = _floats(collision.findtext("pose"), 6)
                sx, sy, sz = _floats(size.text, 3)
                yaw = myaw + lyaw + cyaw
                # 링크/충돌체 오프셋은 모델 yaw 로 돌려서 더한다.
                cos, sin = math.cos(myaw), math.sin(myaw)
                ox, oy = lx + cx, ly + cy
                boxes.append(Box(mx + ox * cos - oy * sin, my + ox * sin + oy * cos,
                                 mz + lz + cz, yaw, sx, sy, sz))
    return boxes


def rasterize(boxes: list[Box], resolution: float, seed: tuple[float, float],
              margin: float = 0.3) -> tuple[list[list[int]], float, float]:
    walls = [b for b in boxes if b.spans_lidar()]
    if not walls:
        raise SystemExit("no box collision spans the lidar height — is this a mesh world?")
    xs = [v for b in walls for v in (b.bounds()[0], b.bounds()[2])]
    ys = [v for b in walls for v in (b.bounds()[1], b.bounds()[3])]
    x0, y0 = min(xs) - margin, min(ys) - margin
    width = int(math.ceil((max(xs) + margin - x0) / resolution))
    height = int(math.ceil((max(ys) + margin - y0) / resolution))

    grid = [[UNKNOWN] * width for _ in range(height)]
    for row in range(height):
        y = y0 + (row + 0.5) * resolution
        for col in range(width):
            x = x0 + (col + 0.5) * resolution
            if any(b.contains(x, y) for b in walls):
                grid[row][col] = OCCUPIED

    # 씨앗에서 닿는 빈칸만 free 다. 방 바깥은 로봇이 본 적 없는 곳이므로 unknown 으로 남긴다
    # — 전부 free 로 칠하면 플래너가 벽 바깥을 질러가는 경로를 낸다.
    scol = int((seed[0] - x0) / resolution)
    srow = int((seed[1] - y0) / resolution)
    if not (0 <= scol < width and 0 <= srow < height) or grid[srow][scol] == OCCUPIED:
        raise SystemExit(f"seed {seed} is outside the world or inside a wall")
    queue = deque([(srow, scol)])
    grid[srow][scol] = FREE
    while queue:
        row, col = queue.popleft()
        for drow, dcol in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            r, c = row + drow, col + dcol
            if 0 <= r < height and 0 <= c < width and grid[r][c] == UNKNOWN:
                grid[r][c] = FREE
                queue.append((r, c))
    return grid, x0, y0


def write_map(grid: list[list[int]], x0: float, y0: float, resolution: float,
              out: Path) -> None:
    height, width = len(grid), len(grid[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".pgm").open("wb") as fh:
        fh.write(b"P5\n# generated by world_to_map.py\n")
        fh.write(f"{width} {height}\n255\n".encode())
        for row in range(height - 1, -1, -1):          # PGM 은 위에서 아래로 쓴다
            fh.write(bytes(0 if v == OCCUPIED else 254 if v == FREE else 205
                           for v in grid[row]))
    out.with_suffix(".yaml").write_text(
        f"image: {out.name}.pgm\n"
        f"mode: trinary\n"
        f"resolution: {resolution}\n"
        f"origin: [{x0}, {y0}, 0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        # 미지 픽셀 205 의 shade 는 (255-205)/255 = 0.196 이다. free_thresh 가 이보다
        # 크면 map_server 가 미지를 자유로 읽어 맵 바깥이 통째로 뚫린 공간이 되고,
        # 플래너는 벽을 지나 밖으로 나가는 지름길을 찾다가 경로를 못 만든다.
        f"free_thresh: 0.196\n",
        encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="world_to_map")
    p.add_argument("world", type=Path)
    p.add_argument("-o", "--out", type=Path, required=True, help="확장자 없는 출력 경로")
    p.add_argument("--resolution", type=float, default=0.05)
    p.add_argument("--seed", default="0,0", help="자유 공간 씨앗 x,y (로봇이 서는 곳)")
    args = p.parse_args(argv)

    sx, sy = (float(v) for v in args.seed.split(","))
    boxes = read_boxes(args.world)
    grid, x0, y0 = rasterize(boxes, args.resolution, (sx, sy))
    write_map(grid, x0, y0, args.resolution, args.out)
    free = sum(1 for row in grid for v in row if v == FREE)
    occupied = sum(1 for row in grid for v in row if v == OCCUPIED)
    print(f"{args.out}.pgm {len(grid[0])}x{len(grid)} "
          f"({len(grid[0]) * args.resolution:.2f}m x {len(grid) * args.resolution:.2f}m) "
          f"origin=({x0:.2f},{y0:.2f}) free={free} occupied={occupied}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
