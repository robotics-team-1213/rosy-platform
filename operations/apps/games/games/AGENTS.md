<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# games (Python package)

## Purpose

Laptop game host (D-90): match loop that observes, referees, applies a policy, clamps the result and sends teleop to CORE. CORE never imports this package and final `cmd_vel` stays in CORE. Soccer is the first game; the heuristic chase is the first policy.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package docstring |
| `catalog.py` | Named plugins: `soccer` game, `heuristic` policy |
| `cli.py` | `games match --config ... [--dry-run] [--ticks N] [--preview] [--stair N] [--observer overhead]` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `field/` | `geometry.py` pitch numbers, `homography.py` pixel quad to metres (no cv2), `types.py` pose/velocity |
| `game/` | Referee: `protocol.py`, `state.py` (phase, observation, result), `soccer.py` 1v1 push-ball referee, `gate.py` last clamp on twists |
| `host/` | `loop.py` match loop, `session.py` arm/tick/always-estop, `transport.py` CORE HTTP adapter, `observer.py`/`hold.py`/`overhead.py` observation sources, `project.py` detections to pitch, `robots.py`, `visibility.py` (D-96 stair 1), `preview.py` board server |
| `policy/` | `protocol.py` contract, `heuristic.py` stage-1 chase |
| `web/` | `index.html`, `board.js`, `styles.css`: laptop match board (D-101), not CORE `/dashboard` |

## For AI Agents

### Working In This Directory

- Import rules, enforced by `operations/apps/games/test/test_games_boundaries.py`: `field`, `game`, `policy` import none of `cv2`, `httpx`, `rclpy`, `core`, `fleet`. OpenCV only in `host/overhead.py`; `host/loop.py` and `host/transport.py` never import it. Do not add `isaac/`.
- Referee `step()` never sees policy twists; policy output always passes through `game/gate.py` before transport.
- `session.py` must always send estop on exit, including on error.
- `visibility.ready` is not FIELD GO.
- `homography.py` is reused by `rosy_vision.project`; keep it pure and dependency-free.

### Testing Requirements

```bash
python -m pytest operations/apps/games/test test/test_rosy_games_surface.py -q
```

Coverage by area: `test_field.py`, `test_homography.py` (field); `test_soccer_game.py`, `test_gate.py` (game); `test_loop.py`, `test_host_session.py`, `test_host_transport.py`, `test_overhead.py`, `test_project.py`, `test_visibility.py`, `test_preview.py` (host); `test_heuristic_policy.py` (policy); `test_catalog.py`, `test_games_cli.py`. `test/fake_host.py` is the shared fake.

### Common Patterns

Protocol classes decouple referee, policy and observer; fakes replace CORE and the camera in tests.

## Dependencies

### Internal

- `config/match.yaml` (sample match config); CORE teleop over HTTP (no import)

### External

- stdlib HTTP for preview; `httpx` in transport; OpenCV only in `host/overhead.py`
