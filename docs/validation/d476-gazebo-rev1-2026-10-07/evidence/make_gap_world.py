#!/usr/bin/env python3
"""Sim-only paint-gap world for D-476 scenario D (sim2real_gaps.yaml G-13).

Copies map_v2_fleet_real.world and lays a visual-only carpet patch (the world's own carpet
material and texture) just above the lane paint over the box [x0, x1] x [y0, y1], so the
camera sees a short gap in both lane lines. No collision, nothing else changes.

    python3 make_gap_world.py SRC_WORLD OUT_WORLD x0 x1 y0 y1
"""
import sys

PATCH = """    <model name="d476_paint_gap">
      <static>true</static>
      <pose>{cx:.4f} {cy:.4f} 0.0016 0 0 0</pose>
      <link name="link">
        <visual name="carpet_patch">
          <geometry><plane><normal>0 0 1</normal><size>{sx:.4f} {sy:.4f}</size></plane></geometry>
          <material>
            <ambient>0.27 0.29 0.27 1</ambient><diffuse>0.27 0.29 0.27 1</diffuse>
            <pbr><metal><albedo_map>model://control/map/map_v2_fleet/textures/carpet_grey.png</albedo_map></metal></pbr>
          </material>
        </visual>
      </link>
    </model>
"""


def main(src, out, x0, x1, y0, y1):
    x0, x1, y0, y1 = map(float, (x0, x1, y0, y1))
    text = open(src).read()
    assert text.count('</world>') == 1 and '<model name="road_lines">' in text
    patch = PATCH.format(cx=(x0+x1)/2, cy=(y0+y1)/2, sx=x1-x0, sy=y1-y0)
    open(out, 'w').write(text.replace('</world>', patch + '  </world>'))


if __name__ == '__main__':
    main(*sys.argv[1:7])
