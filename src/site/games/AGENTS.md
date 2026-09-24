# games

Laptop game host (D-90). CORE does not import this package. Final `cmd_vel` stays in CORE.

`field` / `game` / `policy` must not import `cv2`, `httpx`, `rclpy`, `core`, or `fleet`. OpenCV belongs only in `host/overhead.py`. Homography math lives in `field/homography.py` (no cv2). `host/loop.py` and `host/transport.py` must not import `cv2`. Do not add `isaac/`.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python. No ROS exec_depend |
| `setup.py` / `setup.cfg` | Package install |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `games/field/` | Pitch numbers and homography. No OpenCV, no HTTP |
| `games/game/` | Referee. No policy HTTP |
| `games/policy/` | Heuristic now, neural later |
| `games/catalog.py` | Named plugins: `soccer` game, `heuristic` policy |
| `games/host/` | Match loop, HoldObserver, OverheadCamera, CORE teleop, localhost preview |
| `games/web/` | Laptop match board (D-101). Not CORE `/dashboard` |
| `test/` | ROS-free pytest |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Design: `docs/plans/2026-09-17-robot-soccer-game-host-design.md`. Live camera: `games match --config ... --observer overhead`. Board: `--preview` (D-101).

### Testing Requirements

```bash
python -m pytest src/apps/games/test test/test_rosy_games_surface.py -q
```
