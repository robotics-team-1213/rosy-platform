<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# src

## Purpose

WS2811 lamp node implementation.

## Key Files

| File | Description |
|------|-------------|
| `main_node.cpp` | `RosyLampControl`: ws2811 init, SetLamp service, ColorRGBA sub |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

GPIO 19, DMA 10, 8 LEDs, GRB strip. Sim equivalent is `gz_sim/plugins`.

### Testing Requirements

Hardware or Gazebo plugin.

### Common Patterns

Single C++ translation unit.

## Dependencies

### Internal

- `interfaces/srv/SetLamp`

### External

- rclcpp, rpi_ws281x

<!-- MANUAL: -->
